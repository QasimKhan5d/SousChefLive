"""Tool implementations for SousChef Live.

Each tool modifies session state and emits UI events over WebSocket.
Timer alerts inject SYSTEM text into the Gemini Live session so the
chef persona remains the single voice the cook hears.
"""

import asyncio
import time
from typing import Any, Callable, Awaitable

from server.session_store import (
    SessionContext,
    TimerRecord,
    new_timer_id,
    validate_step_transition,
    VALID_STEPS,
)
from server.observability import emit
from server.proactive import Lane, STEP_GRACE_WINDOW_S, create_candidate

MONITORING_STATUS_MAP = {
    "idle": "Waiting for ingredients",
    "prep": "Monitoring prep",
    "heat": "Monitoring pan heat",
    "sear_side_1": "Watching sear — side 1",
    "flip": "Monitoring flip",
    "sear_side_2": "Watching sear — side 2",
    "baste": "Monitoring baste",
    "rest": "Resting — hands off",
    "done": "Plating",
}

STEP_MILESTONE_PROMPTS = {
    "heat": "SYSTEM: The cook is heating the pan. Give one short reminder to wait for shimmer before adding food.",
    "rest": "SYSTEM: The protein is resting. Give one short reminder to leave it untouched while juices settle.",
}


async def set_timer(
    duration_seconds: int,
    label: str,
    *,
    session: SessionContext,
    text_input_queue: asyncio.Queue,
    send_event: Callable[[dict], Awaitable[None]],
) -> dict:
    effective = duration_seconds
    if session.demo_speed:
        effective = max(1, duration_seconds // 10)

    timer_id = new_timer_id()
    timer = TimerRecord(
        id=timer_id,
        label=label,
        total_seconds=duration_seconds,
        effective_seconds=effective,
        started_at=time.time(),
    )
    session.proactive.mark_timer_started()

    async def _timer_task():
        try:
            prealert_at = effective * 0.8
            await asyncio.sleep(prealert_at)

            prealert_msg = (
                f"SYSTEM: Timer '{label}' is at 80%. "
                f"About {int(effective - prealert_at)} seconds left. Alert the cook now."
            )
            create_candidate(
                session.proactive,
                lane=Lane.MILESTONE_NUDGE,
                trigger_source="timer",
                reason_code="timer_prealert",
                prompt_text=prealert_msg,
                dedupe_key=f"timer_prealert_{timer_id}",
                allow_during_urgent_only=True,
                ignore_step_grace=True,
                ttl_s=max(15.0, effective + 5.0),
            )
            await send_event({
                "type": "state_update",
                **session.to_state_snapshot(),
            })
            emit(
                "backend.timer", "timer_prealert_fired",
                session_id=session.session_id,
                details={"timer_id": timer_id, "label": label,
                         "remaining_seconds": int(effective - prealert_at)},
            )

            await asyncio.sleep(effective - prealert_at)

            expire_msg = (
                f"SYSTEM: Timer '{label}' has expired. Tell the cook to take action now."
            )
            create_candidate(
                session.proactive,
                lane=Lane.MILESTONE_NUDGE,
                trigger_source="timer",
                reason_code="timer_expired",
                prompt_text=expire_msg,
                dedupe_key=f"timer_expire_{timer_id}",
                allow_during_urgent_only=True,
                ignore_step_grace=True,
                ttl_s=max(15.0, effective + 5.0),
            )
            await send_event({
                "type": "state_update",
                **session.to_state_snapshot(),
            })
            emit(
                "backend.timer", "timer_expired",
                session_id=session.session_id,
                details={"timer_id": timer_id, "label": label},
            )
        except asyncio.CancelledError:
            pass

    timer.task = asyncio.create_task(_timer_task())
    session.timers[timer_id] = timer
    session.touch()

    result = {
        "timer_id": timer_id,
        "label": label,
        "effective_seconds": effective,
    }

    # Don't send a tool_call event here — the GeminiLive bridge already
    # sends one for every tool via the event_queue.  Sending it from both
    # places caused duplicate tool_call events on the WebSocket.
    await send_event({"type": "state_update", **session.to_state_snapshot()})
    emit(
        "backend.tools", "state_update_sent",
        session_id=session.session_id,
        details={"trigger": "set_timer", "timer_id": timer_id},
    )

    emit(
        "backend.timer", "timer_scheduled",
        session_id=session.session_id,
        details={"timer_id": timer_id, "label": label,
                 "effective_seconds": effective, "demo_speed": session.demo_speed},
    )

    return result


async def update_cooking_step(
    step_name: str,
    *,
    session: SessionContext,
    send_event: Callable[[dict], Awaitable[None]],
) -> dict:
    if not validate_step_transition(session.current_step, step_name):
        return {
            "error": f"Invalid transition from '{session.current_step}' to '{step_name}'",
            "valid_steps": VALID_STEPS,
        }

    old_step = session.current_step
    session.current_step = step_name
    session.monitoring_status = MONITORING_STATUS_MAP.get(step_name, step_name)
    session.touch()

    if step_name != old_step:
        session.proactive.increment_step_version(step_name=step_name)
        prompt_text = STEP_MILESTONE_PROMPTS.get(step_name)
        if prompt_text:
            create_candidate(
                session.proactive,
                lane=Lane.MILESTONE_NUDGE,
                trigger_source="step_change",
                reason_code=f"step_entered_{step_name}",
                prompt_text=prompt_text,
                dedupe_key=f"step_{step_name}",
                allow_during_urgent_only=True,
                ttl_s=STEP_GRACE_WINDOW_S + 15.0,
            )

    snapshot = session.to_state_snapshot()

    await send_event({"type": "state_update", **snapshot})
    emit(
        "backend.tools", "state_update_sent",
        session_id=session.session_id,
        details={"trigger": "update_cooking_step", "step": step_name},
    )
    emit(
        "backend.tools", "step_updated",
        session_id=session.session_id,
        details={"step": step_name, "monitoring_status": session.monitoring_status},
    )

    return snapshot


async def update_recipe(
    recipe_name: str,
    *,
    session: SessionContext,
    send_event: Callable[[dict], Awaitable[None]],
) -> dict:
    session.recipe_name = recipe_name
    session.touch()
    session.proactive.mark_recipe_selected()

    snapshot = session.to_state_snapshot()
    await send_event({"type": "state_update", **snapshot})
    emit(
        "backend.tools", "state_update_sent",
        session_id=session.session_id,
        details={"trigger": "update_recipe", "recipe_name": recipe_name},
    )

    return snapshot


async def get_cooking_state(
    *,
    session: SessionContext,
) -> dict:
    return session.to_state_snapshot()


def register_session_tools(
    gemini,
    session: SessionContext,
    text_input_queue: asyncio.Queue,
    send_event: Callable[[dict], Awaitable[None]],
) -> None:
    """Wire tool functions with session-specific closures and register them."""

    @gemini.register_tool
    async def update_recipe_tool(recipe_name: str = "", **kwargs) -> dict:
        return await update_recipe(
            recipe_name, session=session, send_event=send_event,
        )

    @gemini.register_tool
    async def set_timer_tool(duration_seconds: int = 120, label: str = "timer", **kwargs) -> dict:
        return await set_timer(
            duration_seconds, label,
            session=session,
            text_input_queue=text_input_queue,
            send_event=send_event,
        )

    @gemini.register_tool
    async def update_cooking_step_tool(step_name: str = "idle", **kwargs) -> dict:
        return await update_cooking_step(
            step_name, session=session, send_event=send_event,
        )

    @gemini.register_tool
    async def get_cooking_state_tool(**kwargs) -> dict:
        return await get_cooking_state(session=session)

    gemini.tool_mapping["update_recipe"] = gemini.tool_mapping.pop("update_recipe_tool")
    gemini.tool_mapping["set_timer"] = gemini.tool_mapping.pop("set_timer_tool")
    gemini.tool_mapping["update_cooking_step"] = gemini.tool_mapping.pop("update_cooking_step_tool")
    gemini.tool_mapping["get_cooking_state"] = gemini.tool_mapping.pop("get_cooking_state_tool")
