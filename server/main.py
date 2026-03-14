"""FastAPI server for SousChef Live.

Serves the frontend from dist/, accepts WebSocket connections for
live cooking sessions, and bridges audio/video/text to Gemini Live.
"""

import asyncio
import base64
import json
import os
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from server.gemini_live import GeminiLive
from server.session_store import (
    get_or_create_session,
    cancel_session_timers,
    cleanup_session_if_idle,
    build_reconnect_primer,
    SessionContext,
    SESSION_MAX_AGE,
)
from server.tools import register_session_tools
from server.prompts import SYSTEM_INSTRUCTION, build_tool_declarations
from server.observability import emit, setup_logging

load_dotenv(override=True)
setup_logging()

MODEL = os.getenv("MODEL", "gemini-2.5-flash-native-audio-latest")
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

app = FastAPI(title="SousChef Live")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("dist/assets"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")
if os.path.exists("dist/audio-processors"):
    app.mount("/audio-processors", StaticFiles(directory="dist/audio-processors"), name="audio-processors")

session_store: dict[str, SessionContext] = {}


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": MODEL, "sessions": len(session_store)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = ""):
    await websocket.accept()

    if not session_id:
        session_id = f"s_{int(time.time())}_{os.urandom(4).hex()}"

    emit("backend.server", "ws_connect", session_id=session_id)

    setup_config = None
    try:
        message = await websocket.receive_text()
        initial_data = json.loads(message)
        if "setup" in initial_data:
            setup_config = initial_data["setup"]
            emit("backend.server", "setup_received", session_id=session_id)
    except Exception as e:
        emit("backend.server", "setup_error", severity="ERROR",
             session_id=session_id, details={"error": str(e)})

    session = get_or_create_session(session_store, session_id)
    is_reconnect = (
        session.recipe_name
        or session.current_step != "idle"
        or len(session.memory.recent_turns) > 0
        or session.timers
    )
    explicit_end = False

    # On reconnect, immediately hydrate the browser with full state snapshot
    if is_reconnect:
        try:
            await websocket.send_json(session.to_state_snapshot())
            emit("backend.server", "state_hydration_sent", session_id=session_id)
        except Exception:
            pass

    if setup_config is None:
        setup_config = {}

    setup_config["system_instruction"] = {
        "parts": [{"text": SYSTEM_INSTRUCTION}]
    }
    setup_config["tools"] = {
        "function_declarations": build_tool_declarations()
    }
    setup_config.setdefault("input_audio_transcription", {})
    setup_config.setdefault("output_audio_transcription", {})
    setup_config.setdefault("generation_config", {
        "response_modalities": ["AUDIO"],
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": "Aoede"}
            }
        },
    })

    audio_input_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    video_input_queue: asyncio.Queue = asyncio.Queue(maxsize=5)
    text_input_queue: asyncio.Queue = asyncio.Queue(maxsize=20)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    gemini = GeminiLive(api_key=api_key, model=MODEL)

    async def send_event(event: dict) -> None:
        try:
            await websocket.send_json(event)
        except Exception:
            pass

    register_session_tools(gemini, session, text_input_queue, send_event)

    # If reconnecting with existing session, prime the model with context
    if is_reconnect:
        primer = build_reconnect_primer(session)
        await text_input_queue.put(primer)
        emit("backend.server", "reconnect_primer_sent", session_id=session_id,
             details={"primer_length": len(primer)})

    async def receive_from_client():
        nonlocal explicit_end
        try:
            while True:
                message = await websocket.receive()
                session.touch()

                if message.get("bytes"):
                    if audio_input_queue.full():
                        try:
                            audio_input_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await audio_input_queue.put(message["bytes"])
                    continue

                if not message.get("text"):
                    continue

                payload = json.loads(message["text"])
                if payload.get("type") == "image":
                    image_data = base64.b64decode(payload["data"])
                    if video_input_queue.full():
                        try:
                            video_input_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await video_input_queue.put(image_data)
                elif payload.get("type") == "text":
                    await text_input_queue.put(payload["text"])
                    emit("backend.server", "text_in_message", session_id=session_id)
                elif payload.get("type") == "control":
                    if _apply_control(session, payload):
                        explicit_end = True
                        return
        except WebSocketDisconnect:
            emit("backend.server", "ws_disconnect", session_id=session_id)
        except Exception as e:
            emit("backend.server", "receive_error", severity="ERROR",
                 session_id=session_id, details={"error": str(e)})

    async def send_audio(data: bytes):
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    async def run_session():
        async for event in gemini.start_session(
            audio_input_queue=audio_input_queue,
            video_input_queue=video_input_queue,
            text_input_queue=text_input_queue,
            audio_output_callback=send_audio,
            event_callback=send_event,
            setup_config=setup_config,
            session_context=session,
        ):
            if event:
                await send_event(event)

    client_task = asyncio.create_task(receive_from_client())
    session_task = asyncio.create_task(run_session())
    try:
        done, pending = await asyncio.wait(
            [client_task, session_task],
            timeout=SESSION_MAX_AGE,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            emit("backend.server", "session_timeout", session_id=session_id)
            explicit_end = True
            try:
                await websocket.close(code=1000, reason="Session max age reached")
            except Exception:
                pass
        for task in done:
            if task.exception():
                emit("backend.server", "session_error", severity="ERROR",
                     session_id=session_id,
                     details={"error": str(task.exception())})
        if session_task in (done or set()) and not explicit_end and not session.ended:
            emit("backend.server", "gemini_session_ended_unexpectedly",
                 session_id=session_id, severity="WARNING")
            try:
                await websocket.close(code=1011, reason="Gemini session ended")
            except Exception:
                pass
    except Exception as e:
        emit("backend.server", "session_error", severity="ERROR",
             session_id=session_id, details={"error": str(e)})
    finally:
        client_task.cancel()
        session_task.cancel()
        try:
            await client_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await session_task
        except (asyncio.CancelledError, Exception):
            pass

        if explicit_end or session.ended:
            cancel_session_timers(session)
            if session_id in session_store:
                del session_store[session_id]
            emit("backend.server", "session_ended", session_id=session_id)
        else:
            session.touch()
            emit("backend.server", "session_kept_alive",
                 session_id=session_id,
                 details={"reason": "transient_disconnect"})


def _apply_control(session: SessionContext, payload: dict) -> bool:
    """Apply a control action. Returns True if session should end."""
    action = payload.get("action")
    value = payload.get("value")
    if action == "demo_speed":
        session.demo_speed = bool(value)
        emit("backend.server", "control_applied", session_id=session.session_id,
             details={"action": action, "value": value})
    elif action == "end_session":
        session.ended = True
        emit("backend.server", "control_end_session", session_id=session.session_id)
        return True
    return False


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    file_path = f"dist/{full_path}"
    if full_path and os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    return {"error": "Frontend not built. Run 'npm run build' first."}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
