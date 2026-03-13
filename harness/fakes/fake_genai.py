"""Fake Gemini Live adapter for deterministic testing.

Implements the subset of the real genai Client/Session contract that
SousChef Live actually uses. Supports scripted responses, tool calls,
interrupts, and injected delays/failures.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class FakeInlineData:
    data: bytes
    mime_type: str = "audio/pcm"


@dataclass
class FakePart:
    inline_data: FakeInlineData | None = None
    text: str | None = None


@dataclass
class FakeModelTurn:
    parts: list[FakePart] = field(default_factory=list)


@dataclass
class FakeInputTranscription:
    text: str = ""


@dataclass
class FakeOutputTranscription:
    text: str = ""


@dataclass
class FakeFunctionCall:
    name: str = ""
    args: dict = field(default_factory=dict)
    id: str = "fc_001"


@dataclass
class FakeToolCall:
    function_calls: list[FakeFunctionCall] = field(default_factory=list)


@dataclass
class FakeServerContent:
    model_turn: FakeModelTurn | None = None
    input_transcription: FakeInputTranscription | None = None
    output_transcription: FakeOutputTranscription | None = None
    turn_complete: bool = False
    interrupted: bool = False


@dataclass
class FakeResponse:
    server_content: FakeServerContent | None = None
    tool_call: FakeToolCall | None = None


class FakeLiveSession:
    """Deterministic live session that replays scripted events."""

    def __init__(self, script: list[dict] | None = None):
        self.script = script or []
        self.sent_audio: list[Any] = []
        self.sent_video: list[Any] = []
        self.sent_text: list[str] = []
        self.sent_tool_responses: list[Any] = []
        self._script_index = 0
        self._script_done = False
        self._closed = False

    async def send_realtime_input(self, audio=None, video=None):
        if audio:
            self.sent_audio.append(audio)
        if video:
            self.sent_video.append(video)

    async def send(self, input: str = "", end_of_turn: bool = False):
        self.sent_text.append(input)

    async def send_tool_response(self, function_responses=None):
        self.sent_tool_responses.append(function_responses)

    async def receive(self) -> AsyncIterator[FakeResponse]:
        if self._script_done:
            await asyncio.sleep(999999)
            return

        while self._script_index < len(self.script):
            entry = self.script[self._script_index]
            self._script_index += 1

            delay = entry.get("delay", 0)
            if delay:
                await asyncio.sleep(delay)

            if entry.get("error"):
                raise Exception(entry["error"])

            response = self._build_response(entry)
            if response:
                yield response

        self._script_done = True

    def _build_response(self, entry: dict) -> FakeResponse | None:
        etype = entry.get("type")

        if etype == "audio":
            data = entry.get("data", b"\x00" * 100)
            if isinstance(data, str):
                data = data.encode()
            return FakeResponse(
                server_content=FakeServerContent(
                    model_turn=FakeModelTurn(
                        parts=[FakePart(inline_data=FakeInlineData(data=data))]
                    )
                )
            )
        elif etype == "input_transcription":
            return FakeResponse(
                server_content=FakeServerContent(
                    input_transcription=FakeInputTranscription(text=entry.get("text", ""))
                )
            )
        elif etype == "output_transcription":
            return FakeResponse(
                server_content=FakeServerContent(
                    output_transcription=FakeOutputTranscription(text=entry.get("text", ""))
                )
            )
        elif etype == "turn_complete":
            return FakeResponse(
                server_content=FakeServerContent(turn_complete=True)
            )
        elif etype == "interrupted":
            return FakeResponse(
                server_content=FakeServerContent(interrupted=True)
            )
        elif etype == "tool_call":
            return FakeResponse(
                tool_call=FakeToolCall(
                    function_calls=[
                        FakeFunctionCall(
                            name=entry.get("name", ""),
                            args=entry.get("args", {}),
                            id=entry.get("id", "fc_001"),
                        )
                    ]
                )
            )
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._closed = True


class FakeLiveConnect:
    """Fake aio.live.connect() context manager."""

    def __init__(self, script: list[dict] | None = None):
        self.script = script
        self.session = FakeLiveSession(script)

    def connect(self, model: str, config: Any = None) -> "FakeLiveConnect":
        return self

    async def __aenter__(self) -> FakeLiveSession:
        return self.session

    async def __aexit__(self, *args):
        pass


class FakeAioLive:
    def __init__(self, script: list[dict] | None = None):
        self.script = script

    def connect(self, model: str, config: Any = None) -> FakeLiveConnect:
        return FakeLiveConnect(self.script)


class FakeAio:
    def __init__(self, script: list[dict] | None = None):
        self.live = FakeAioLive(script)


class FakeGenaiClient:
    """Drop-in replacement for genai.Client in fake mode."""

    def __init__(self, script: list[dict] | None = None, **kwargs):
        self.aio = FakeAio(script)
