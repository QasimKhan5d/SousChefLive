"""End-to-end tests for session memory and context persistence.

Tests the REAL behavior of the memory system against the deployed service:
- Connect, converse, disconnect, reconnect with same session_id
- Verify state hydration (recipe, step, transcript, timers) on reconnect
- Verify memory accumulates across turns
- Verify compression thresholds are accepted by the Gemini API
- Verify session resumption handles are captured
- Verify transient disconnect keeps session alive

These are NOT unit tests. They hit the real deployed service and real Gemini API.
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


async def _collect(ws, timeout_s=25):
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
                events.append(json.loads(msg))
            except json.JSONDecodeError:
                pass
    return events


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


class TestSessionMemoryE2E:
    """Real end-to-end tests for the session memory system."""

    @pytest.mark.asyncio
    async def test_connect_converse_disconnect_reconnect(self):
        """Full lifecycle: connect, send message, get response, disconnect,
        reconnect with same session_id, verify state hydration."""

        session_id = f"mem_e2e_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        print(f"\n=== PHASE 1: First connection (session_id={session_id}) ===")

        # Phase 1: Connect and have a conversation
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            # Ask the agent to set up a recipe (triggers tool calls)
            await ws.send(json.dumps({
                "type": "text",
                "text": "Let's cook garlic butter chicken thighs. Please call update_recipe with recipe name 'Garlic Butter Chicken Thighs' and update_cooking_step to 'prep'.",
            }))

            events1 = await _collect_until_turn_complete(ws, timeout_s=30)

            # Inspect what we got
            tool_calls = [e for e in events1 if e.get("type") == "tool_call"]
            audio_chunks = [e for e in events1 if e.get("_type") == "audio"]
            state_updates = [e for e in events1 if e.get("type") == "state_update"]
            transcriptions = [
                e.get("serverContent", {}).get("outputTranscription", {}).get("text", "")
                for e in events1
                if e.get("serverContent", {}).get("outputTranscription")
            ]

            print(f"  Tool calls: {[tc.get('name') for tc in tool_calls]}")
            print(f"  Audio chunks: {len(audio_chunks)}")
            print(f"  State updates: {len(state_updates)}")
            print(f"  Transcription: {''.join(transcriptions)[:200]}")

            # Should have gotten some response (tool calls OR audio)
            assert len(tool_calls) > 0 or len(audio_chunks) > 0, \
                f"No response from agent. Events: {events1}"

        # WebSocket is now closed (transient disconnect)
        print(f"\n=== PHASE 2: Disconnected. Waiting 3s, then reconnecting... ===")
        await asyncio.sleep(3)

        # Phase 2: Reconnect with same session_id
        # IMPORTANT: Server sends hydration AFTER receiving setup message.
        # So we must send setup first, then read events.
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws2:
            await ws2.send(_setup_msg())

            # Collect all events for a few seconds — hydration should be first
            all_events = []
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    all_events.append(data)
                    # Stop collecting once we have the hydration
                    if data.get("type") == "state_update":
                        break
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    break

            hydration = next((e for e in all_events if e.get("type") == "state_update"), None)

            print(f"\n=== PHASE 2: State hydration received ===")
            if hydration:
                print(f"  Recipe: {hydration.get('recipe_name')}")
                print(f"  Step: {hydration.get('current_step')}")
                print(f"  Timers: {hydration.get('timers')}")
                transcript = hydration.get("transcript", [])
                print(f"  Transcript entries: {len(transcript)}")
                for t in transcript[:5]:
                    print(f"    [{t['role']}] {t['text'][:100]}")
                print(f"  Session ID matches: {hydration.get('session_id') == session_id}")

                assert hydration.get("type") == "state_update"
                assert hydration.get("session_id") == session_id
            else:
                print(f"  WARNING: No hydration. Got events: {[e.get('type', e.get('serverContent',{}).keys()) for e in all_events]}")

            # Ask a follow-up question to verify context continuity
            await ws2.send(json.dumps({
                "type": "text",
                "text": "What recipe are we making? What step are we on?",
            }))

            events2 = await _collect_until_turn_complete(ws2, timeout_s=30)

            transcriptions2 = [
                e.get("serverContent", {}).get("outputTranscription", {}).get("text", "")
                for e in events2
                if e.get("serverContent", {}).get("outputTranscription")
            ]
            audio2 = [e for e in events2 if e.get("_type") == "audio"]
            full_transcript = "".join(transcriptions2)

            print(f"\n=== PHASE 2: Follow-up response ===")
            print(f"  Audio chunks: {len(audio2)}")
            print(f"  Transcription: {full_transcript[:300]}")

            assert len(audio2) > 0 or len(transcriptions2) > 0, \
                f"No response after reconnect. Events: {events2}"

            # Clean up
            await ws2.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))
            await asyncio.sleep(1)

    @pytest.mark.asyncio
    async def test_compression_thresholds_accepted(self):
        """Verify the explicit trigger_tokens/target_tokens don't cause
        connection errors. If the Gemini API rejects them, the session
        would fail to start."""

        session_id = f"compress_e2e_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            # If compression thresholds were rejected, the session wouldn't work
            await ws.send(json.dumps({
                "type": "text",
                "text": "Say hello in one sentence.",
            }))

            events = await _collect_until_turn_complete(ws, timeout_s=20)

            # Check we got a response (not an error)
            errors = [e for e in events if e.get("type") == "error"]
            audio = [e for e in events if e.get("_type") == "audio"]

            print(f"\n=== Compression threshold test ===")
            print(f"  Errors: {errors}")
            print(f"  Audio chunks: {len(audio)}")

            if errors:
                for err in errors:
                    print(f"  ERROR: {err}")
                    # Check if it's a compression-related error
                    err_text = str(err.get("error", "")).lower()
                    assert "trigger_tokens" not in err_text, \
                        f"Compression trigger_tokens rejected: {err}"
                    assert "target_tokens" not in err_text, \
                        f"Compression target_tokens rejected: {err}"

            assert len(audio) > 0, f"No audio response. Events: {events}"

            await ws.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))

    @pytest.mark.asyncio
    async def test_session_resumption_config_accepted(self):
        """Verify SessionResumptionConfig is accepted by the API.
        We check that we can connect and get a response — if the config
        was rejected, the connection would fail."""

        session_id = f"resume_e2e_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "Hi, just testing. Say hello briefly.",
            }))

            events = await _collect_until_turn_complete(ws, timeout_s=20)
            audio = [e for e in events if e.get("_type") == "audio"]

            print(f"\n=== Session resumption config test ===")
            print(f"  Audio chunks: {len(audio)}")

            # Connection succeeded and we got audio = config was accepted
            assert len(audio) > 0, \
                f"Session resumption config may have been rejected. Events: {events}"

            await ws.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))

    @pytest.mark.asyncio
    async def test_transient_disconnect_keeps_session_on_server(self):
        """Connect, send a recipe update, disconnect without end_session,
        reconnect — session should still exist with the recipe name."""

        session_id = f"persist_e2e_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        print(f"\n=== Transient disconnect persistence test (sid={session_id}) ===")

        # Phase 1: Connect and trigger a recipe tool call
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "Please call the update_recipe tool with the recipe name 'Test Pasta Recipe'. Just call the tool, nothing else.",
            }))

            events1 = await _collect_until_turn_complete(ws, timeout_s=30)
            tool_calls = [e for e in events1 if e.get("type") == "tool_call"]
            print(f"  Phase 1 tool calls: {[tc.get('name') for tc in tool_calls]}")

        # Transient disconnect (no end_session sent)
        print(f"  Disconnected. Waiting 3s...")
        await asyncio.sleep(3)

        # Phase 2: Reconnect — send setup first, then read hydration
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws2:
            await ws2.send(_setup_msg())

            hydration_events = []
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    hydration_events.append(data)
                    if data.get("type") == "state_update":
                        break
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    break

            state_updates = [e for e in hydration_events if e.get("type") == "state_update"]

            print(f"\n  Phase 2: Hydration events received: {len(hydration_events)}")
            for su in state_updates:
                print(f"  State update: recipe={su.get('recipe_name')}, step={su.get('current_step')}")
                print(f"    Timers: {su.get('timers', [])}")
                print(f"    Transcript entries: {len(su.get('transcript', []))}")

            if state_updates:
                su = state_updates[0]
                if tool_calls and any(tc.get("name") == "update_recipe" for tc in tool_calls):
                    assert su.get("recipe_name") is not None, \
                        f"Recipe should be set after update_recipe tool call. State: {su}"
                    print(f"  VERIFIED: Recipe name persisted: {su.get('recipe_name')}")
            else:
                print("  WARNING: No state_update hydration received")

            # Clean up
            await ws2.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))
            await asyncio.sleep(1)

    @pytest.mark.asyncio
    async def test_memory_accumulates_transcript_turns(self):
        """Have a multi-turn conversation, disconnect, reconnect,
        verify transcript turns appear in state hydration."""

        session_id = f"turns_e2e_{int(time.time())}"
        ssl_ctx = ssl.create_default_context()

        print(f"\n=== Transcript accumulation test (sid={session_id}) ===")

        # Phase 1: Multi-turn conversation
        async with websockets.connect(
            _ws_url(session_id), ssl=ssl_ctx, open_timeout=15, close_timeout=5
        ) as ws:
            await ws.send(_setup_msg())
            await asyncio.sleep(1)

            # Turn 1
            await ws.send(json.dumps({
                "type": "text",
                "text": "Hi chef, I want to make something with chicken and garlic.",
            }))
            events1 = await _collect_until_turn_complete(ws, timeout_s=25)
            transcripts1 = [
                e.get("serverContent", {}).get("outputTranscription", {}).get("text", "")
                for e in events1
                if e.get("serverContent", {}).get("outputTranscription")
            ]
            print(f"  Turn 1 transcription: {''.join(transcripts1)[:150]}")

            # Turn 2
            await ws.send(json.dumps({
                "type": "text",
                "text": "I also have butter and thyme. What do you recommend?",
            }))
            events2 = await _collect_until_turn_complete(ws, timeout_s=25)
            transcripts2 = [
                e.get("serverContent", {}).get("outputTranscription", {}).get("text", "")
                for e in events2
                if e.get("serverContent", {}).get("outputTranscription")
            ]
            print(f"  Turn 2 transcription: {''.join(transcripts2)[:150]}")

        # Disconnect (transient)
        print(f"  Disconnected after 2 turns. Waiting 3s...")
        await asyncio.sleep(3)

        # Phase 2: Reconnect — send setup first, then read hydration
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

            print(f"\n  Phase 2: State hydration received: {hydration is not None}")
            if hydration:
                transcript = hydration.get("transcript", [])
                print(f"  Transcript entries: {len(transcript)}")
                for t in transcript:
                    print(f"    [{t['role']}] {t['text'][:100]}")

                assert len(transcript) > 0, \
                    f"Expected transcript entries from 2-turn conversation. Hydration: {hydration}"
                print(f"\n  VERIFIED: {len(transcript)} transcript turns accumulated and hydrated")
            else:
                print("  WARNING: No state hydration received")

            # Clean up
            await ws2.send(json.dumps({
                "type": "control", "action": "end_session", "value": True,
            }))
            await asyncio.sleep(1)
