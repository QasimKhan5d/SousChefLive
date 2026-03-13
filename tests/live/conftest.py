"""Shared fixtures and helpers for live/deployed tests.

Provides WebSocket connection helpers, image loading, event collection,
and assertion utilities shared across all live test files.
"""

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
    "https://souschef-live-504591545979.us-central1.run.app",
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


def load_image_b64(filename: str) -> str:
    path = FIXTURES_DIR / filename
    if not path.exists():
        pytest.skip(f"Fixture image {filename} not found at {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image_message(filename: str) -> str:
    return json.dumps({
        "type": "image",
        "data": load_image_b64(filename),
        "mimeType": "image/jpeg",
    })


def text_message(text: str) -> str:
    return json.dumps({"type": "text", "text": text})


def control_message(action: str, value=True) -> str:
    return json.dumps({"type": "control", "action": action, "value": value})


async def collect_events(ws, timeout_s: float = 35) -> list[dict]:
    """Read events until turn_complete or timeout."""
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


async def collect_events_multi_turn(ws, timeout_s: float = 35) -> list[dict]:
    """Like collect_events but keeps going after turnComplete (returns all events)."""
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
        except json.JSONDecodeError:
            events.append({"_type": "raw", "data": msg[:200]})

    return events


def extract_output_transcription(events: list[dict]) -> str:
    """Concatenate all output transcription text from events."""
    parts = []
    for e in events:
        sc = e.get("serverContent", {})
        ot = sc.get("outputTranscription", {})
        if ot and ot.get("text"):
            parts.append(ot["text"])
    return " ".join(parts).strip()


def extract_input_transcription(events: list[dict]) -> str:
    parts = []
    for e in events:
        sc = e.get("serverContent", {})
        it = sc.get("inputTranscription", {})
        if it and it.get("text"):
            parts.append(it["text"])
    return " ".join(parts).strip()


def extract_tool_calls(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tool_call"]


def extract_tool_names(events: list[dict]) -> set[str]:
    return {tc["name"] for tc in extract_tool_calls(events)}


def extract_state_updates(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "state_update"]


def extract_audio_chunks(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("_type") == "audio_chunk"]


def assert_any_keyword(text: str, keywords: list[str], min_matches: int = 1):
    """Assert that at least min_matches keywords appear in text (case-insensitive)."""
    text_lower = text.lower()
    found = [kw for kw in keywords if kw.lower() in text_lower]
    assert len(found) >= min_matches, (
        f"Expected at least {min_matches} of {keywords} in transcription, "
        f"found {found}. Full text: {text[:500]}"
    )


def assert_no_forbidden(text: str, forbidden: list[str] | None = None):
    """Assert that none of the forbidden phrases appear."""
    if forbidden is None:
        forbidden = ["as an ai", "i'm an ai", "language model", "i cannot help"]
    text_lower = text.lower()
    for phrase in forbidden:
        assert phrase not in text_lower, (
            f"Forbidden phrase '{phrase}' found in transcription: {text[:500]}"
        )


def assert_concise(text: str, max_words: int = 80):
    """Assert response is concise."""
    word_count = len(text.split())
    assert word_count <= max_words, (
        f"Response too long ({word_count} words, max {max_words}): {text[:300]}"
    )


def ssl_context():
    return ssl.create_default_context()
