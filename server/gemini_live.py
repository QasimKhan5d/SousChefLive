"""GeminiLive bridge class for SousChef Live.

Wraps the google-genai SDK to proxy audio/video/text between the
FastAPI WebSocket endpoint and the Gemini Live API session.
Supports session resumption, context compression with explicit
thresholds, and an inner retry loop for upstream reconnects.
"""

import asyncio
import inspect
import json
import logging
import os
import re
from typing import Any, Callable, Optional

import google.genai as genai
from google.genai import types

from server.memory import run_compaction
from server.observability import emit

_CTRL_TOKEN_RE = re.compile(r"<ctrl\d+>")

GEMINI_TRIGGER_TOKENS = int(os.getenv("GEMINI_TRIGGER_TOKENS", "108000"))
GEMINI_TARGET_TOKENS = int(os.getenv("GEMINI_TARGET_TOKENS", "80000"))
MAX_UPSTREAM_RETRIES = 3


def _clean_transcription(text: str | None) -> str:
    """Strip control-token artifacts the model sometimes emits."""
    if not text:
        return ""
    return _CTRL_TOKEN_RE.sub("", text).strip()

logger = logging.getLogger(__name__)

LIVE_BACKEND_MODE = os.getenv("LIVE_BACKEND_MODE", "real")


class _UpstreamResumableDisconnect(Exception):
    """Raised when the upstream Gemini connection drops but can be resumed."""
    pass


class GeminiLive:
    def __init__(self, api_key: str, model: str, input_sample_rate: int = 16000,
                 fake_script: list[dict] | None = None):
        self.api_key = api_key
        self.model = model
        self.input_sample_rate = input_sample_rate
        self.tool_mapping: dict[str, Callable] = {}

        if LIVE_BACKEND_MODE == "fake":
            from harness.fakes.fake_genai import FakeGenaiClient
            self.client = FakeGenaiClient(script=fake_script or [])
        else:
            self.client = genai.Client(api_key=api_key)

    def register_tool(self, func: Callable) -> Callable:
        self.tool_mapping[func.__name__] = func
        return func

    async def start_session(
        self,
        audio_input_queue: asyncio.Queue,
        video_input_queue: asyncio.Queue,
        text_input_queue: asyncio.Queue,
        audio_output_callback: Callable,
        event_callback: Callable,
        setup_config: Optional[dict] = None,
        session_context: Any = None,
    ):
        """Connect to Gemini Live and proxy data between queues and session.

        Yields events (JSON dicts) to the caller for forwarding to the client.
        Contains an inner retry loop: if the upstream Gemini connection drops
        but a resumption handle is available, it reconnects automatically
        while keeping the input queues intact.
        """
        retry_count = 0

        while True:
            handle = session_context.resumption_handle if session_context else None
            config = self._build_live_config(
                setup_config or {},
                resumption_handle=handle,
            )

            emit("backend.bridge", "live_connect_start",
                 details={"model": self.model, "has_handle": handle is not None,
                           "retry": retry_count})

            resumable_error = False

            try:
                async with self.client.aio.live.connect(
                    model=self.model, config=config
                ) as session:
                    emit("backend.bridge", "live_connect_ok")
                    retry_count = 0

                    event_queue: asyncio.Queue = asyncio.Queue()

                    async def send_audio():
                        try:
                            while True:
                                chunk = await audio_input_queue.get()
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=chunk,
                                        mime_type=f"audio/pcm;rate={self.input_sample_rate}",
                                    )
                                )
                        except asyncio.CancelledError:
                            pass

                    async def send_video():
                        try:
                            while True:
                                frame = await video_input_queue.get()
                                await session.send_realtime_input(
                                    video=types.Blob(data=frame, mime_type="image/jpeg")
                                )
                        except asyncio.CancelledError:
                            pass

                    async def send_text():
                        try:
                            while True:
                                text = await text_input_queue.get()
                                await session.send_client_content(
                                    turns=types.Content(
                                        role="user",
                                        parts=[types.Part(text=text)]
                                    ),
                                    turn_complete=True,
                                )
                        except asyncio.CancelledError:
                            pass

                    async def receive_loop():
                        nonlocal resumable_error
                        try:
                            while True:
                                async for response in session.receive():
                                    # Capture session resumption handles
                                    if hasattr(response, "session_resumption_update") and response.session_resumption_update:
                                        sru = response.session_resumption_update
                                        if hasattr(sru, "new_handle") and sru.new_handle:
                                            if session_context:
                                                session_context.resumption_handle = sru.new_handle
                                                emit("backend.bridge", "resumption_handle_captured")

                                    # Handle GoAway signals
                                    if hasattr(response, "go_away") and response.go_away:
                                        time_left = getattr(response.go_away, "time_left", None)
                                        emit("backend.bridge", "go_away_received",
                                             details={"time_left": str(time_left)})
                                        await event_queue.put({
                                            "type": "go_away",
                                            "time_left": str(time_left) if time_left else None,
                                        })

                                    sc = response.server_content
                                    tc = response.tool_call

                                    if sc:
                                        if sc.model_turn:
                                            for part in sc.model_turn.parts:
                                                if part.inline_data:
                                                    if inspect.iscoroutinefunction(audio_output_callback):
                                                        await audio_output_callback(part.inline_data.data)
                                                    else:
                                                        audio_output_callback(part.inline_data.data)
                                                    emit("backend.bridge", "audio_out_chunk")

                                        if sc.input_transcription:
                                            txt = _clean_transcription(sc.input_transcription.text)
                                            if session_context and txt:
                                                session_context.memory.add_turn("cook", txt)
                                            if txt:
                                                await event_queue.put({
                                                    "serverContent": {
                                                        "inputTranscription": {
                                                            "text": txt,
                                                            "finished": True,
                                                        }
                                                    }
                                                })

                                        if sc.output_transcription:
                                            txt = _clean_transcription(sc.output_transcription.text)
                                            if session_context and txt:
                                                session_context.memory.add_turn("chef", txt)
                                            if txt:
                                                await event_queue.put({
                                                    "serverContent": {
                                                        "outputTranscription": {
                                                            "text": txt,
                                                            "finished": True,
                                                        }
                                                    }
                                                })

                                        if sc.turn_complete:
                                            await event_queue.put({"serverContent": {"turnComplete": True}})
                                            emit("backend.bridge", "turn_complete")

                                            if session_context and session_context.memory.needs_compaction():
                                                asyncio.create_task(
                                                    run_compaction(session_context.memory, self.api_key)
                                                )

                                        if sc.interrupted:
                                            await event_queue.put({"serverContent": {"interrupted": True}})
                                            emit("backend.bridge", "interrupt_received")

                                    if tc:
                                        function_responses = []
                                        for fc in tc.function_calls:
                                            func_name = fc.name
                                            args = fc.args or {}

                                            emit(
                                                "backend.bridge", "tool_call_received",
                                                details={"name": func_name, "args": args},
                                            )

                                            if func_name in self.tool_mapping:
                                                try:
                                                    tool_func = self.tool_mapping[func_name]
                                                    if inspect.iscoroutinefunction(tool_func):
                                                        result = await tool_func(**args)
                                                    else:
                                                        loop = asyncio.get_running_loop()
                                                        result = await loop.run_in_executor(
                                                            None, lambda: tool_func(**args)
                                                        )
                                                    emit(
                                                        "backend.bridge", "tool_call_completed",
                                                        details={"name": func_name, "result": result},
                                                    )
                                                except Exception as e:
                                                    result = {"error": str(e)}
                                                    emit(
                                                        "backend.bridge", "tool_call_failed",
                                                        severity="ERROR",
                                                        details={"name": func_name, "error": str(e)},
                                                    )

                                                function_responses.append(
                                                    types.FunctionResponse(
                                                        name=func_name,
                                                        id=fc.id,
                                                        response={"result": result},
                                                    )
                                                )
                                                await event_queue.put({
                                                    "type": "tool_call",
                                                    "name": func_name,
                                                    "args": args,
                                                    "result": result,
                                                })

                                        if function_responses:
                                            await session.send_tool_response(
                                                function_responses=function_responses
                                            )

                        except Exception as e:
                            error_str = str(e)
                            if session_context and session_context.resumption_handle:
                                resumable_error = True
                                emit("backend.bridge", "upstream_resumable_disconnect",
                                     details={"error": error_str})
                            else:
                                emit("backend.bridge", "live_connect_error",
                                     severity="ERROR", details={"error": error_str})
                                await event_queue.put({"type": "error", "error": error_str})
                        finally:
                            if not resumable_error:
                                await event_queue.put(None)

                    tasks = [
                        asyncio.create_task(send_audio()),
                        asyncio.create_task(send_video()),
                        asyncio.create_task(send_text()),
                        asyncio.create_task(receive_loop()),
                    ]

                    try:
                        while True:
                            event = await event_queue.get()
                            if event is None:
                                break
                            yield event
                    finally:
                        for t in tasks:
                            t.cancel()
                        for t in tasks:
                            try:
                                await t
                            except (asyncio.CancelledError, Exception):
                                pass

            except Exception as e:
                if session_context and session_context.resumption_handle:
                    resumable_error = True
                    emit("backend.bridge", "upstream_connect_failed_resumable",
                         details={"error": str(e)})
                else:
                    emit("backend.bridge", "live_connect_error",
                         severity="ERROR", details={"error": str(e)})
                    raise

            if resumable_error:
                retry_count += 1
                if retry_count > MAX_UPSTREAM_RETRIES:
                    emit("backend.bridge", "upstream_retries_exhausted")
                    return
                delay = min(2 ** retry_count, 8)
                emit("backend.bridge", "upstream_reconnecting",
                     details={"retry": retry_count, "delay": delay})
                await asyncio.sleep(delay)
                continue
            else:
                break

    def _build_live_config(
        self,
        setup_config: dict,
        resumption_handle: str | None = None,
    ) -> types.LiveConnectConfig:
        config_args: dict[str, Any] = {
            "response_modalities": [types.Modality.AUDIO],
        }

        if "generation_config" in setup_config:
            gc = setup_config["generation_config"]
            if "response_modalities" in gc:
                config_args["response_modalities"] = [
                    types.Modality(m) for m in gc["response_modalities"]
                ]
            if "speech_config" in gc:
                try:
                    vn = gc["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"]
                    config_args["speech_config"] = types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=vn)
                        )
                    )
                except (KeyError, TypeError):
                    pass

        if "system_instruction" in setup_config:
            try:
                text = setup_config["system_instruction"]["parts"][0]["text"]
                config_args["system_instruction"] = types.Content(
                    parts=[types.Part(text=text)]
                )
            except (KeyError, IndexError, TypeError):
                pass

        if "tools" in setup_config:
            try:
                tc = setup_config["tools"]
                if "function_declarations" in tc:
                    fds = []
                    for fd in tc["function_declarations"]:
                        fds.append(types.FunctionDeclaration(
                            name=fd.get("name"),
                            description=fd.get("description"),
                            parameters=fd.get("parameters"),
                        ))
                    config_args["tools"] = [types.Tool(function_declarations=fds)]
            except Exception as e:
                logger.warning(f"Error parsing tools config: {e}")

        if "input_audio_transcription" in setup_config:
            config_args["input_audio_transcription"] = types.AudioTranscriptionConfig()
        if "output_audio_transcription" in setup_config:
            config_args["output_audio_transcription"] = types.AudioTranscriptionConfig()

        if "realtime_input_config" in setup_config:
            ric = setup_config["realtime_input_config"]
            if "automatic_activity_detection" in ric:
                aad = ric["automatic_activity_detection"]
                config_args["realtime_input_config"] = types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=aad.get("disabled", False),
                    )
                )

        config_args["context_window_compression"] = types.ContextWindowCompressionConfig(
            trigger_tokens=GEMINI_TRIGGER_TOKENS,
            sliding_window=types.SlidingWindow(target_tokens=GEMINI_TARGET_TOKENS),
        )

        if resumption_handle:
            config_args["session_resumption"] = types.SessionResumptionConfig(
                handle=resumption_handle,
            )
        else:
            config_args["session_resumption"] = types.SessionResumptionConfig()

        return types.LiveConnectConfig(**config_args)
