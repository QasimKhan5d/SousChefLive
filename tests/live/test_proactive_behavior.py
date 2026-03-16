"""Live deployment tests for proactive behavior on the real app."""

import asyncio
import base64
import json
import os
import ssl
import time
from pathlib import Path

import pytest
import websockets

DEPLOYED_URL = os.environ.get(
    "DEPLOYED_URL",
    "https://souschef-live-5z4a6smnda-uc.a.run.app",
)
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "harness" / "fixtures" / "images"


def ws_url(session_id: str = "") -> str:
    base = DEPLOYED_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws?session_id={session_id}"


def setup_message() -> str:
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


def text_message(text: str) -> str:
    return json.dumps({"type": "text", "text": text})


def image_message(filename: str) -> str:
    path = FIXTURES_DIR / filename
    if not path.exists():
        pytest.skip(f"Missing image fixture: {path}")
    return json.dumps({
        "type": "image",
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mimeType": "image/jpeg",
    })


def ssl_context():
    return ssl.create_default_context()


async def collect_until_turn_complete(ws, timeout_s: float = 35) -> list[dict]:
    events = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
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


async def collect_window(ws, duration_s: float) -> list[dict]:
    events = []
    deadline = time.time() + duration_s
    while time.time() < deadline:
        timeout = min(3.0, max(0.1, deadline - time.time()))
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            continue
        except websockets.exceptions.ConnectionClosed:
            break
        if isinstance(msg, bytes):
            events.append({"_type": "audio_chunk", "size": len(msg)})
            continue
        try:
            events.append(json.loads(msg))
        except json.JSONDecodeError:
            events.append({"_type": "raw", "data": msg[:200]})
    return events


def extract_output_transcription(events: list[dict]) -> str:
    parts = []
    for event in events:
        sc = event.get("serverContent", {})
        text = sc.get("outputTranscription", {}).get("text")
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def extract_tool_calls(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("type") == "tool_call"]


def extract_proactive_meta(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("type") == "proactive_meta"]


def extract_audio_chunks(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("_type") == "audio_chunk"]


pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)


class TestRunIdCorrelation:
    @pytest.mark.asyncio
    async def test_run_id_sent_on_connect(self):
        sid = f"proactive_runid_{int(time.time())}"
        async with websockets.connect(ws_url(sid), ssl=ssl_context()) as ws:
            await ws.send(setup_message())
            events = await collect_window(ws, duration_s=5)
            run_id = [event for event in events if event.get("type") == "run_id"]
            assert run_id, f"No run_id message received. Events: {events[:10]}"
            assert run_id[0]["run_id"].startswith("run_")


class TestNegativeControls:
    @pytest.mark.asyncio
    async def test_idle_session_stays_silent_for_45_seconds(self):
        sid = f"idle_silence_{int(time.time())}"
        async with websockets.connect(ws_url(sid), ssl=ssl_context()) as ws:
            await ws.send(setup_message())
            events = await collect_window(ws, duration_s=45)

        proactive = extract_proactive_meta(events)
        output = extract_output_transcription(events)
        audio = extract_audio_chunks(events)
        assert proactive == [], f"Idle session produced proactive_meta: {proactive[:5]}"
        assert output == "", f"Idle session produced unsolicited output: {output}"
        assert audio == [], f"Idle session produced unsolicited audio: {audio[:5]}"

    @pytest.mark.asyncio
    async def test_recipe_selection_then_silence_has_no_unsolicited_chatter(self):
        sid = f"recipe_silence_{int(time.time())}"
        async with websockets.connect(ws_url(sid), ssl=ssl_context()) as ws:
            await ws.send(setup_message())
            await ws.send(text_message(
                "I have chicken thighs, garlic, and butter. Suggest a good dish and get me ready to cook."
            ))
            initial = await collect_until_turn_complete(ws, timeout_s=30)
            initial_output = extract_output_transcription(initial)
            assert initial_output, f"No initial response received. Events: {initial[:20]}"

            silence = await collect_window(ws, duration_s=25)

        proactive = extract_proactive_meta(silence)
        output = extract_output_transcription(silence)
        audio = extract_audio_chunks(silence)
        assert proactive == [], f"Unexpected proactive_meta after recipe turn: {proactive[:5]}"
        assert output == "", f"Unexpected unsolicited speech after recipe turn: {output}"
        assert audio == [], f"Unexpected unsolicited audio after recipe turn: {audio[:5]}"

    @pytest.mark.asyncio
    async def test_safe_prep_image_does_not_trigger_proactive_warning(self):
        sid = f"prep_safe_{int(time.time())}"
        async with websockets.connect(ws_url(sid), ssl=ssl_context()) as ws:
            await ws.send(setup_message())
            await ws.send(text_message(
                "We're making garlic butter chicken thighs. I am still in prep, just getting ingredients ready."
            ))
            initial = await collect_until_turn_complete(ws, timeout_s=30)
            assert extract_output_transcription(initial), f"No prep setup response. Events: {initial[:20]}"

            await ws.send(image_message("good_knife_grip.jpg"))
            safety_window = await collect_window(ws, duration_s=25)

        proactive = extract_proactive_meta(safety_window)
        output = extract_output_transcription(safety_window)
        assert proactive == [], f"Safe prep image triggered proactive_meta: {proactive[:5]}"
        assert output == "", f"Safe prep image triggered unsolicited speech: {output}"


class TestTimerMilestones:
    @pytest.mark.asyncio
    async def test_timer_produces_milestone_and_user_visible_output(self):
        sid = f"timer_milestone_{int(time.time())}"
        async with websockets.connect(ws_url(sid), ssl=ssl_context()) as ws:
            await ws.send(setup_message())
            await ws.send(json.dumps({"type": "control", "action": "demo_speed", "value": True}))

            await ws.send(text_message(
                "We are cooking garlic butter chicken thighs. Please start the rest step and set a 20 second timer labelled rest test."
            ))
            first_turn = await collect_until_turn_complete(ws, timeout_s=35)
            timer_tools = [call for call in extract_tool_calls(first_turn) if call.get("name") == "set_timer"]
            assert timer_tools, f"No set_timer tool call in first turn. Events: {first_turn[:30]}"

            # Demo speed: 20s -> 2s effective. Prealert at 1.6s, expire at 2s. Collect 25s to allow variance.
            window = await collect_window(ws, duration_s=25)

        proactive = extract_proactive_meta(window)
        timer_meta = [
            event for event in proactive
            if event.get("reason_code") in {"timer_prealert", "timer_expired"}
        ]
        output = extract_output_transcription(window).lower()
        audio = extract_audio_chunks(window)

        # At least one of: proactive_meta with timer reason, or user-visible timer-related output
        has_proactive = bool(timer_meta)
        has_visible = bool(audio) or (
            bool(output) and ("timer" in output or "rest" in output or "seconds" in output)
        )
        assert has_proactive or has_visible, (
            f"No timer milestone observed. proactive_meta={proactive}, output={output!r}, "
            f"audio_chunks={len(audio)}, window_events={len(window)}"
        )
