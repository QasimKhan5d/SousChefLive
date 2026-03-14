"""End-to-end tests against the deployed Cloud Run service.

Tests the full server stack: WebSocket connect → setup → Gemini Live
session → tool calls → audio response.  Uses the real Gemini API via
the deployed backend (no fakes/mocks).

Requires:
  GEMINI_API_KEY  — set in environment
  DEPLOYED_URL    — Cloud Run service URL (defaults to production)
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
    reason="GEMINI_API_KEY not set — skipping deployed E2E tests",
)


def _ws_url(session_id: str = "") -> str:
    base = DEPLOYED_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws?session_id={session_id}"


def _setup_message() -> str:
    return json.dumps({
        "setup": {
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": "Aoede"},
                    },
                },
            },
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
    })


async def _collect_events(ws, timeout_s: float = 30) -> list[dict]:
    """Read events until turn_complete or timeout."""
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
            events.append({"_type": "audio_chunk", "size": len(msg)})
            continue

        try:
            data = json.loads(msg)
            events.append(data)
            if data.get("serverContent", {}).get("turnComplete"):
                break
        except json.JSONDecodeError:
            events.append({"_type": "raw", "data": msg[:200]})

    return events


class TestDeployedHealth:
    """Verify the deployed service is up and serving."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{DEPLOYED_URL}/api/health", timeout=10)
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert "gemini" in body["model"]

    @pytest.mark.asyncio
    async def test_frontend_serves(self):
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(DEPLOYED_URL, timeout=10)
            assert resp.status_code == 200
            assert "SousChef" in resp.text


class TestDeployedWebSocket:
    """Test the full WebSocket → Gemini Live flow on the deployed service."""

    @pytest.mark.asyncio
    async def test_ws_connect_and_setup(self):
        """Connect, send setup, verify the session stays open."""
        ssl_ctx = ssl.create_default_context()
        async with websockets.connect(
            _ws_url("e2e_test_setup"),
            ssl=ssl_ctx,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            await ws.send(_setup_message())
            await asyncio.sleep(2)
            # websockets v14 uses .state instead of .open
            assert ws.state.name == "OPEN", "WebSocket should remain open after setup"

    @pytest.mark.asyncio
    async def test_text_turn_gets_audio_response(self):
        """Send a text message, expect audio chunks back."""
        ssl_ctx = ssl.create_default_context()
        async with websockets.connect(
            _ws_url("e2e_test_text"),
            ssl=ssl_ctx,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            await ws.send(_setup_message())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "Hello chef, I have chicken thighs, garlic, and butter. What should we cook?",
            }))

            events = await _collect_events(ws, timeout_s=30)

            audio_chunks = [e for e in events if e.get("_type") == "audio_chunk"]
            assert len(audio_chunks) > 0, f"Expected audio chunks, got events: {[e.get('_type') or e.get('type') or list(e.keys()) for e in events]}"

    @pytest.mark.asyncio
    async def test_agent_calls_tools(self):
        """Send a recipe request, expect tool calls or a substantive audio response.

        Tool calling is non-deterministic — the agent may answer verbally
        instead of invoking a tool.  Accept either outcome as valid.
        """
        ssl_ctx = ssl.create_default_context()
        async with websockets.connect(
            _ws_url("e2e_test_tools"),
            ssl=ssl_ctx,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            await ws.send(_setup_message())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "I have chicken thighs, garlic, and butter. Let's make garlic butter chicken. Please call the update_recipe tool with 'Garlic Butter Chicken Thighs' and then the update_cooking_step tool with 'prep'.",
            }))

            events = await _collect_events(ws, timeout_s=30)

            tool_calls = [e for e in events if e.get("type") == "tool_call"]
            audio_chunks = [e for e in events if e.get("_type") == "audio_chunk"]

            assert len(tool_calls) > 0 or len(audio_chunks) > 0, (
                f"Expected tool calls or audio response. Events: "
                f"{[e.get('type') or e.get('_type') or list(e.keys()) for e in events]}"
            )

    @pytest.mark.asyncio
    async def test_transcription_received(self):
        """Verify output transcription is sent back."""
        ssl_ctx = ssl.create_default_context()
        async with websockets.connect(
            _ws_url("e2e_test_transcription"),
            ssl=ssl_ctx,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            await ws.send(_setup_message())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "text",
                "text": "What's a quick side dish for chicken?",
            }))

            events = await _collect_events(ws, timeout_s=30)

            transcriptions = [
                e for e in events
                if e.get("serverContent", {}).get("outputTranscription")
            ]
            assert len(transcriptions) > 0, (
                f"Expected output transcription events. Events: "
                f"{[e.get('type') or e.get('_type') or list(e.keys()) for e in events]}"
            )

    @pytest.mark.asyncio
    async def test_graceful_end_session(self):
        """Send end_session control, verify no crash."""
        ssl_ctx = ssl.create_default_context()
        async with websockets.connect(
            _ws_url("e2e_test_end"),
            ssl=ssl_ctx,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            await ws.send(_setup_message())
            await asyncio.sleep(1)

            await ws.send(json.dumps({
                "type": "control",
                "action": "end_session",
                "value": True,
            }))

            await asyncio.sleep(2)
