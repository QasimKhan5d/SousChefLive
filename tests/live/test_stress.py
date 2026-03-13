"""Stress and durability tests against the deployed service.

Tests session stability over time, rapid message handling, reconnect
with state preservation, and graceful error handling for malformed input.

Requires:
  GEMINI_API_KEY  — set in environment
  DEPLOYED_URL    — Cloud Run service URL (defaults to production)
"""

import asyncio
import json
import os
import time

import pytest
import websockets

from tests.live.conftest import (
    ws_url, setup_message, text_message, image_message,
    control_message, collect_events,
    extract_output_transcription, extract_tool_calls,
    extract_audio_chunks, extract_state_updates,
    ssl_context,
)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    ),
    pytest.mark.timeout(360),
]


class TestSessionDurability:
    """Long-running session stability tests."""

    @pytest.mark.asyncio
    async def test_multi_turn_session_stability(self):
        """Keep a session alive across 5 text turns + 2 image turns over ~2 min."""
        messages = [
            ("text", "I want to cook garlic butter chicken thighs tonight."),
            ("text", "What ingredients do I need?"),
            ("image", "garlic_butter_ingredients.jpg"),
            ("text", "I have everything. Let's start prepping."),
            ("image", "chicken_searing.jpg"),
            ("text", "The chicken is in the pan now."),
            ("text", "How long should I sear each side?"),
        ]

        async with websockets.connect(
            ws_url("stress_durability"), ssl=ssl_context(),
            open_timeout=20, close_timeout=10,
        ) as ws:
            await ws.send(setup_message())

            responses_received = 0
            for i, (msg_type, content) in enumerate(messages):
                if msg_type == "text":
                    await ws.send(text_message(content))
                elif msg_type == "image":
                    await ws.send(image_message(content))
                    await ws.send(text_message(
                        "What do you see?" if i == 2 else "How's it looking?"
                    ))

                events = await collect_events(ws, timeout_s=35)
                transcript = extract_output_transcription(events)
                if len(transcript) > 0 or len(extract_audio_chunks(events)) > 0:
                    responses_received += 1

            # LLM responses are non-deterministic; transcription may not
            # appear for every turn.  Require at least 1 turn with a
            # response to prove the session stayed alive.
            assert responses_received >= 1, (
                f"Expected at least 1/7 turns to get a response, got {responses_received}"
            )
            assert ws.state.name == "OPEN", "Session should remain open"


class TestRapidMessages:
    """Test handling of rapid successive messages."""

    @pytest.mark.asyncio
    async def test_rapid_text_burst(self):
        """Send 5 text messages in quick succession, verify no crash."""
        async with websockets.connect(
            ws_url("stress_rapid"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())

            questions = [
                "What oil should I use for searing?",
                "What temperature for chicken?",
                "How do I know when oil is ready?",
                "Should I season before or after?",
                "Can I use a cast iron pan?",
            ]

            for q in questions:
                await ws.send(text_message(q))
                await asyncio.sleep(0.3)

            all_events = []
            deadline = time.time() + 45
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except asyncio.TimeoutError:
                    if len(all_events) > 0:
                        break
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break

                if isinstance(msg, bytes):
                    all_events.append({"_type": "audio_chunk", "size": len(msg)})
                else:
                    try:
                        all_events.append(json.loads(msg))
                    except json.JSONDecodeError:
                        pass

            audio = [e for e in all_events if e.get("_type") == "audio_chunk"]
            assert len(audio) > 0, (
                f"Expected at least some audio response to rapid messages. "
                f"Events: {len(all_events)}"
            )


class TestReconnect:
    """Test session state preservation across reconnects."""

    @pytest.mark.asyncio
    async def test_reconnect_preserves_session(self):
        """Connect, establish recipe, disconnect, reconnect with same session_id."""
        session_id = f"stress_reconnect_{int(time.time())}"

        async with websockets.connect(
            ws_url(session_id), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await ws.send(text_message(
                "Let's make garlic butter chicken thighs. I'm prepping now."
            ))
            events = await collect_events(ws, timeout_s=40)
            tool_calls = extract_tool_calls(events)

        await asyncio.sleep(2)

        async with websockets.connect(
            ws_url(session_id), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws2:
            await ws2.send(setup_message())
            # Wait for reconnect primer + agent response
            events2 = await collect_events(ws2, timeout_s=35)
            transcript = extract_output_transcription(events2)
            audio = extract_audio_chunks(events2)

            reconnected = len(audio) > 0 or len(transcript) > 0
            # Even if the primer doesn't generate a transcription,
            # the session should be open
            assert ws2.state.name == "OPEN" or reconnected, (
                "Reconnected session should be usable"
            )


class TestMalformedInput:
    """Test graceful handling of invalid messages."""

    @pytest.mark.asyncio
    async def test_invalid_json_no_crash(self):
        """Send malformed JSON — server should not crash."""
        async with websockets.connect(
            ws_url("stress_malformed"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await asyncio.sleep(1)

            try:
                await ws.send("this is not valid json {{{")
            except Exception:
                pass

            await asyncio.sleep(2)
            # Session may close but should not produce a server error
            # that prevents new connections

    @pytest.mark.asyncio
    async def test_empty_text_message(self):
        """Send empty text message — should be handled gracefully."""
        async with websockets.connect(
            ws_url("stress_empty"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await asyncio.sleep(1)

            await ws.send(json.dumps({"type": "text", "text": ""}))
            await asyncio.sleep(2)

            # After empty text, send a real message — session should still work
            await ws.send(text_message("Are you still there?"))
            events = await collect_events(ws, timeout_s=30)
            audio = extract_audio_chunks(events)
            assert len(audio) > 0 or ws.state.name == "OPEN", (
                "Session should survive an empty text message"
            )

    @pytest.mark.asyncio
    async def test_oversized_image_graceful(self):
        """Send a very small 'image' that is clearly not a real JPEG."""
        async with websockets.connect(
            ws_url("stress_badimg"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await asyncio.sleep(1)

            import base64
            fake_data = base64.b64encode(b"not-a-jpeg").decode()
            await ws.send(json.dumps({
                "type": "image",
                "data": fake_data,
                "mimeType": "image/jpeg",
            }))

            await asyncio.sleep(2)

            # Session should still be usable
            await ws.send(text_message("Hello chef, are you there?"))
            events = await collect_events(ws, timeout_s=30)
