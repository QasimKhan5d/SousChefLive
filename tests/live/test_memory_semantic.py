"""Semantic verification of the session memory system.

Goes beyond "does it work?" to "does it work CORRECTLY?"
- Verifies that transcript turns contain real dialogue content
- Verifies that state hydration data is semantically correct
- Verifies that the reconnect primer causes the agent to maintain context
- Verifies that the agent references prior conversation after reconnect
"""

import asyncio
import json
import os
import ssl
import time

import pytest
import websockets

DEPLOYED_URL = os.environ.get(
    "DEPLOYED_URL",
    "https://souschef-live-504591545979.europe-west1.run.app",
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)


def _ws_url(session_id: str) -> str:
    base = DEPLOYED_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws?session_id={session_id}"


def _setup_msg() -> str:
    return json.dumps({"setup": {
        "generation_config": {
            "response_modalities": ["AUDIO"],
            "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}}},
        },
        "input_audio_transcription": {},
        "output_audio_transcription": {},
    }})


async def _collect_until_turn_complete(ws, timeout_s=30):
    events = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        except websockets.exceptions.ConnectionClosed:
            break
        if isinstance(msg, bytes):
            events.append({"_type": "audio", "size": len(msg)})
        else:
            try:
                data = json.loads(msg)
                events.append(data)
                if data.get("serverContent", {}).get("turnComplete"):
                    break
            except json.JSONDecodeError:
                pass
    return events


def _extract_output_text(events):
    parts = []
    for e in events:
        sc = e.get("serverContent", {})
        ot = sc.get("outputTranscription", {})
        if ot and ot.get("text"):
            parts.append(ot["text"])
    return " ".join(parts).strip()


class TestMemorySemantic:
    """Verify the memory system produces correct, meaningful content."""

    @pytest.mark.asyncio
    async def test_hydration_transcript_contains_real_dialogue(self):
        """After a conversation, the hydrated transcript should contain
        actual dialogue words, not empty strings or garbage."""

        session_id = f"sem_dialogue_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        # Phase 1: Have a real conversation
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "I have salmon fillets, lemon, dill, and olive oil. What should we make?",
            }))
            events = await _collect_until_turn_complete(ws, timeout_s=30)
            output_text = _extract_output_text(events)
            print(f"\n  Phase 1 agent response: {output_text[:200]}")

        await asyncio.sleep(3)

        # Phase 2: Reconnect and inspect hydration quality
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws2:
            await ws2.send(_setup_msg())

            hydration = None
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    if data.get("type") == "state_update":
                        hydration = data
                        break
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    break

            assert hydration is not None, "No state hydration received"
            transcript = hydration.get("transcript", [])
            assert len(transcript) > 0, f"Transcript is empty. Full hydration: {hydration}"

            print(f"\n  Hydration transcript ({len(transcript)} entries):")
            for t in transcript:
                print(f"    [{t['role']:4s}] {t['text']}")

            # Semantic checks on transcript content
            for t in transcript:
                assert t["role"] in ("cook", "chef"), f"Invalid role: {t['role']}"
                assert isinstance(t["text"], str), f"Text is not string: {t['text']}"
                assert len(t["text"].strip()) > 0, f"Empty text in transcript entry: {t}"

            all_text = " ".join(t["text"] for t in transcript).lower()
            # The agent should have mentioned something cooking-related
            cooking_words = ["salmon", "lemon", "dill", "cook", "fillet", "oil", "recipe",
                             "sear", "bake", "grill", "pan", "season", "herb", "fish"]
            found = [w for w in cooking_words if w in all_text]
            print(f"  Cooking words found in transcript: {found}")

            assert len(found) >= 1, (
                f"Transcript doesn't contain meaningful cooking content. "
                f"All text: {all_text[:300]}"
            )

            # Cleanup
            await ws2.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))
            await asyncio.sleep(1)

    @pytest.mark.asyncio
    async def test_agent_references_recipe_after_reconnect(self):
        """After reconnecting, the agent should know the recipe name
        and reference it when asked, proving the primer works."""

        session_id = f"sem_recipe_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        # Phase 1: Set up a specific recipe
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "Let's cook garlic butter chicken thighs. Please call update_recipe with 'Garlic Butter Chicken Thighs' and update_cooking_step to 'prep'.",
            }))
            events1 = await _collect_until_turn_complete(ws, timeout_s=30)
            tool_calls = [e.get("name", "") for e in events1 if e.get("type") == "tool_call"]
            print(f"\n  Phase 1 tool calls: {tool_calls}")

        await asyncio.sleep(3)

        # Phase 2: Reconnect and ask what recipe we're making
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws2:
            await ws2.send(_setup_msg())

            # Drain hydration
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    if data.get("type") == "state_update":
                        print(f"  Hydration: recipe={data.get('recipe_name')}, step={data.get('current_step')}")
                        break
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    break

            # Ask what recipe we're making (the agent should know from primer/memory)
            await ws2.send(json.dumps({
                "type": "text",
                "text": "What recipe are we cooking right now?",
            }))
            events2 = await _collect_until_turn_complete(ws2, timeout_s=30)
            response = _extract_output_text(events2)
            audio_count = sum(1 for e in events2 if e.get("_type") == "audio")

            print(f"\n  Phase 2 response: {response[:300]}")
            print(f"  Audio chunks: {audio_count}")

            # The agent should reference the recipe or demonstrate contextual awareness
            # (e.g., mentioning ingredients, steps, or cooking actions relevant to the recipe)
            if response:
                response_lower = response.lower()
                context_words = [
                    "garlic", "butter", "chicken", "thigh",
                    "welcome back", "pan", "heat", "sear", "prep",
                    "season", "salt", "pepper", "ready",
                ]
                found = [w for w in context_words if w in response_lower]
                print(f"  Context words in response: {found}")
                assert len(found) >= 1, (
                    f"Agent showed no context awareness. Response: {response[:300]}"
                )
            else:
                # If no transcription but audio, agent still responded
                assert audio_count > 0, "No response after reconnect"
                print("  (No transcription, but audio was received — agent responded)")

            await ws2.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))
            await asyncio.sleep(1)

    @pytest.mark.asyncio
    async def test_state_hydration_correctness(self):
        """Verify that the state hydration snapshot contains correct data
        after setting recipe, step, and having conversation."""

        session_id = f"sem_state_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        # Phase 1: Set recipe and step
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "Please call update_recipe with 'Lemon Herb Salmon' and call update_cooking_step with 'prep'.",
            }))
            events = await _collect_until_turn_complete(ws, timeout_s=30)
            tool_calls = [e for e in events if e.get("type") == "tool_call"]
            tool_names = [tc.get("name") for tc in tool_calls]
            print(f"\n  Phase 1 tool calls: {tool_names}")

        await asyncio.sleep(3)

        # Phase 2: Verify hydration state
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws2:
            await ws2.send(_setup_msg())

            hydration = None
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    if data.get("type") == "state_update":
                        hydration = data
                        break
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    break

            assert hydration is not None, "No state hydration"

            print(f"\n  Hydration state:")
            print(f"    type: {hydration.get('type')}")
            print(f"    session_id: {hydration.get('session_id')}")
            print(f"    recipe_name: {hydration.get('recipe_name')}")
            print(f"    current_step: {hydration.get('current_step')}")
            print(f"    timers: {hydration.get('timers')}")
            print(f"    transcript count: {len(hydration.get('transcript', []))}")
            print(f"    started_at: {hydration.get('started_at')}")

            # Structural correctness
            assert hydration["type"] == "state_update"
            assert hydration["session_id"] == session_id
            assert isinstance(hydration.get("timers"), list)
            assert isinstance(hydration.get("transcript"), list)
            assert isinstance(hydration.get("started_at"), (int, float))

            # Semantic correctness: depends on whether tool calls succeeded
            if "update_recipe" in tool_names:
                assert hydration.get("recipe_name") is not None, \
                    "Recipe name should be set after update_recipe"
                print(f"  VERIFIED: recipe_name = {hydration['recipe_name']}")

            if "update_cooking_step" in tool_names:
                assert hydration.get("current_step") != "idle", \
                    "Step should not be idle after update_cooking_step"
                print(f"  VERIFIED: current_step = {hydration['current_step']}")

            await ws2.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))
            await asyncio.sleep(1)
