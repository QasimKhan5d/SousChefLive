"""In-memory session store and data models for SousChef Live.

Holds per-session recipe context, cooking step, timers, and conversation
memory. Keyed by session_id, cleaned up after idle TTL or max age expiry.
"""

import asyncio
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from server.memory import SessionMemory
from server.observability import emit

VALID_STEPS = [
    "idle", "prep", "heat", "sear_side_1", "flip",
    "sear_side_2", "baste", "rest", "done",
]

SESSION_IDLE_TTL = int(os.getenv("SESSION_IDLE_TTL", "300"))
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "3600"))


@dataclass
class TimerRecord:
    id: str
    label: str
    total_seconds: int
    effective_seconds: int
    started_at: float
    task: asyncio.Task | None = None

    @property
    def remaining_seconds(self) -> float:
        elapsed = time.time() - self.started_at
        return max(0.0, self.effective_seconds - elapsed)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "total_seconds": self.total_seconds,
            "effective_seconds": self.effective_seconds,
            "started_at": self.started_at,
            "remaining_seconds": round(self.remaining_seconds, 1),
        }


@dataclass
class SessionContext:
    session_id: str
    recipe_name: str | None = None
    current_step: str = "idle"
    monitoring_status: str = "Waiting for ingredients"
    demo_speed: bool = False
    timers: dict[str, TimerRecord] = field(default_factory=dict)
    memory: SessionMemory = field(default_factory=SessionMemory)
    resumption_handle: str | None = None
    started_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    ended: bool = False

    def touch(self) -> None:
        self.last_seen_at = time.time()

    def is_expired(self) -> bool:
        now = time.time()
        if now - self.last_seen_at > SESSION_IDLE_TTL:
            return True
        if now - self.started_at > SESSION_MAX_AGE:
            return True
        return False

    def to_state_snapshot(self) -> dict:
        return {
            "type": "state_update",
            "session_id": self.session_id,
            "recipe_name": self.recipe_name,
            "current_step": self.current_step,
            "monitoring_status": self.monitoring_status,
            "demo_speed": self.demo_speed,
            "timers": [t.to_dict() for t in self.timers.values()],
            "started_at": self.started_at,
            "transcript": [
                {"role": t.role, "text": t.text}
                for t in list(self.memory.recent_turns)[-30:]
            ],
        }


def get_or_create_session(
    store: dict[str, SessionContext], session_id: str
) -> SessionContext:
    if session_id in store:
        ctx = store[session_id]
        ctx.touch()
        emit("backend.session", "session_resumed", session_id=session_id)
        return ctx

    ctx = SessionContext(session_id=session_id)
    store[session_id] = ctx
    emit("backend.session", "session_created", session_id=session_id)
    return ctx


def cancel_session_timers(session: SessionContext) -> None:
    for timer in session.timers.values():
        if timer.task and not timer.task.done():
            timer.task.cancel()
    emit(
        "backend.session", "timers_cancelled",
        session_id=session.session_id,
        details={"timer_count": len(session.timers)},
    )


async def cleanup_session_if_idle(
    store: dict[str, SessionContext], session_id: str
) -> bool:
    ctx = store.get(session_id)
    if not ctx:
        return False
    if ctx.is_expired():
        cancel_session_timers(ctx)
        del store[session_id]
        emit("backend.session", "session_cleanup", session_id=session_id)
        return True
    return False


def build_reconnect_primer(session: SessionContext) -> str:
    """Build a rich text primer for re-establishing context after reconnect.

    Used as fallback when session resumption handle is unavailable.
    """
    parts = ["SYSTEM: Resume kitchen coaching for the same cooking session."]
    if session.recipe_name:
        parts.append(f"Current recipe: {session.recipe_name}.")
    parts.append(f"Current step: {session.current_step}.")

    active = [
        f"{t.label} has {int(t.remaining_seconds)}s left"
        for t in session.timers.values()
        if t.remaining_seconds > 0
    ]
    if active:
        parts.append(f"Active timers: {'; '.join(active)}.")

    memory_text = session.memory.format_for_primer()
    if memory_text:
        parts.append(f"\n{memory_text}")

    primer = "\n".join(parts)
    if len(primer) > 8000:
        primer = primer[:8000] + "\n[...truncated]"
    return primer


def validate_step_transition(current: str, target: str) -> bool:
    if target not in VALID_STEPS:
        return False
    if current == target:
        return True
    try:
        ci = VALID_STEPS.index(current)
        ti = VALID_STEPS.index(target)
        return ti >= ci
    except ValueError:
        return False


def new_timer_id() -> str:
    return f"tmr_{uuid.uuid4().hex[:6]}"
