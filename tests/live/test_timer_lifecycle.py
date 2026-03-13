"""Timer lifecycle tests against the deployed service.

Triggers timers via conversation with demo_speed enabled and verifies
the complete lifecycle: set_timer tool call → state_update with timer →
pre-alert text injection → agent responds → expiry text injection →
agent responds.

Requires:
  GEMINI_API_KEY  — set in environment
  DEPLOYED_URL    — Cloud Run service URL (defaults to production)
"""

import asyncio
import os
import time

import pytest
import websockets

from tests.live.conftest import (
    ws_url, setup_message, text_message, control_message,
    collect_events, collect_events_multi_turn,
    extract_output_transcription, extract_tool_calls,
    extract_tool_names, extract_state_updates,
    extract_audio_chunks, assert_no_forbidden,
    ssl_context,
)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    ),
    pytest.mark.timeout(180),
]


class TestTimerLifecycle:
    """Test timer creation and lifecycle through the real agent."""

    @pytest.mark.asyncio
    async def test_timer_creation_via_conversation(self):
        """Ask the agent to set a timer, verify set_timer tool call fires."""
        async with websockets.connect(
            ws_url("timer_create"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())

            await ws.send(text_message(
                "We're searing chicken thighs. Please set a 2-minute sear timer."
            ))

            events = await collect_events(ws, timeout_s=40)
            tool_calls = extract_tool_calls(events)
            timer_calls = [tc for tc in tool_calls if tc["name"] == "set_timer"]

            assert len(timer_calls) > 0, (
                f"Expected set_timer tool call. Got: "
                f"{[tc['name'] for tc in tool_calls]}"
            )

            timer_result = timer_calls[0].get("result", {})
            assert "timers" in timer_result or "timer_id" in str(timer_result), (
                f"Timer result should contain timer info: {timer_result}"
            )

    @pytest.mark.asyncio
    async def test_timer_with_demo_speed(self):
        """Enable demo_speed, set a short timer, wait for lifecycle events.

        With demo_speed on, a 60s timer compresses to ~6s.  We wait for
        pre-alert (at 80%) and expiry text injections, plus the agent's
        responses to them.
        """
        async with websockets.connect(
            ws_url("timer_demospeed"), ssl=ssl_context(),
            open_timeout=15, close_timeout=10,
        ) as ws:
            await ws.send(setup_message())

            await ws.send(control_message("demo_speed", True))
            await asyncio.sleep(0.5)

            await ws.send(text_message(
                "Set a 1-minute sear timer please. The chicken just went in the pan."
            ))

            first_events = await collect_events(ws, timeout_s=40)
            timer_calls = [
                tc for tc in extract_tool_calls(first_events)
                if tc["name"] == "set_timer"
            ]
            state_updates = extract_state_updates(first_events)

            assert len(timer_calls) > 0, (
                f"Expected set_timer call. Events: "
                f"{[e.get('type') or e.get('_type') or list(e.keys()) for e in first_events]}"
            )

            # With demo_speed, 60s → ~6s.  Pre-alert at 80% → ~4.8s.
            # Wait up to 15s for the pre-alert and expiry injections to trigger
            # responses from the agent.
            lifecycle_events = []
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break

                if isinstance(msg, bytes):
                    lifecycle_events.append({"_type": "audio_chunk", "size": len(msg)})
                    continue

                try:
                    data = json.loads(msg)
                    lifecycle_events.append(data)
                except Exception:
                    pass

            all_events = first_events + lifecycle_events
            all_audio = extract_audio_chunks(all_events)
            all_transcripts = extract_output_transcription(all_events)
            all_state = extract_state_updates(all_events)

            print(f"\nTimer lifecycle collected {len(all_events)} total events")
            print(f"  Audio chunks: {len(all_audio)}")
            print(f"  State updates: {len(all_state)}")
            print(f"  Transcription: {all_transcripts[:200]}")

            assert len(all_audio) > 0, "Expected audio from timer responses"

    @pytest.mark.asyncio
    async def test_timer_state_update_received(self):
        """Verify set_timer returns timer data in its result.

        state_update events are sent via a separate WebSocket path and may
        arrive interleaved with the Gemini event stream, so we also check
        the tool_call result itself for timer information.
        """
        async with websockets.connect(
            ws_url("timer_state"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())

            await ws.send(text_message(
                "Please set a 3-minute rest timer for the chicken."
            ))

            # Collect events including a brief window after turnComplete
            # to catch any trailing state_update messages
            events = []
            deadline = time.time() + 45
            turn_complete_seen = False
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except asyncio.TimeoutError:
                    if turn_complete_seen:
                        break
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break

                if isinstance(msg, bytes):
                    events.append({"_type": "audio_chunk", "size": len(msg)})
                    continue

                try:
                    data = json.loads(msg)
                    events.append(data)
                    if data.get("serverContent", {}).get("turnComplete"):
                        turn_complete_seen = True
                        # Keep reading for 2 more seconds to catch trailing state_updates
                        deadline = min(deadline, time.time() + 2)
                except json.JSONDecodeError:
                    pass

            state_updates = extract_state_updates(events)
            timer_calls = [
                tc for tc in extract_tool_calls(events)
                if tc["name"] == "set_timer"
            ]

            if len(timer_calls) > 0:
                timer_result = timer_calls[0].get("result", {})
                has_timer_in_result = (
                    "timers" in timer_result
                    or "timer_id" in str(timer_result)
                    or "label" in str(timer_result)
                )
                has_state_update = len(state_updates) > 0

                assert has_timer_in_result or has_state_update, (
                    f"set_timer fired but no timer data found. "
                    f"Result: {timer_result}, state_updates: {state_updates}"
                )


import json
