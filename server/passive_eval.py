"""Out-of-band passive evaluator for SousChef Live.

Runs at low frequency during active cooking phases. Analyzes the latest
video frame and session state to produce structured proactive candidates.
NEVER speaks directly — only creates candidates for the coordinator.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Optional

from server.observability import emit
from server.proactive import (
    PASSIVE_EVAL_ENABLED,
    PASSIVE_EVAL_INTERVAL,
    PASSIVE_EVAL_MODEL,
    PASSIVE_EVAL_STEPS,
    PERSISTENCE_ROUNDS,
    Lane,
    ProactiveState,
    create_candidate,
)

logger = logging.getLogger(__name__)

EVAL_TIMEOUT_S = 8
MIN_FRAME_AGE_S = 2.0

EVAL_PROMPT = """You are a kitchen safety and coaching evaluator. You are shown a single frame from a live cooking session.

Current cooking step: {step}
Recipe: {recipe}
Active timers: {timers}

Analyze the frame for cooking issues ONLY. Return a JSON object with exactly these keys:
- "action": a short coaching instruction (string), or null if nothing needs attention
- "urgency": "urgent_now" if there is an immediate safety/burning issue, "important_next_gap" if there is a non-urgent cooking mistake, or null if no action needed
- "confidence": a float 0.0-1.0 indicating how confident you are
- "reason_code": one of ["food_burning","heavy_smoke","dangerous_heat","contamination_obvious","unsafe_knife_grip","pan_cold_with_food","pan_overcrowded","technique_wrong","normal_activity","scene_change","unclear"]
- "reason": a brief explanation of what you see

Rules:
- Only flag CONCRETE, VISIBLE issues. Do not guess or speculate.
- "urgent_now" is for: clearly burning food, heavy smoke, dangerous heat, obvious contamination, UNSAFE KNIFE GRIP (flat fingers exposed to blade, not curled).
- "unsafe_knife_grip": use when fingers are flat or exposed to the blade instead of curled (claw grip). Action: "Pause — curl your fingertips for safety."
- "important_next_gap" is for: cold pan with food in it, overcrowded pan, other wrong technique (not knife safety).
- Return {{"action": null}} if the cooking looks normal or you cannot clearly identify an issue.
- Do NOT flag normal kitchen activity like chopping, moving around, or adjusting equipment.
- Do NOT flag aesthetic preferences or minor technique variations.

Respond with ONLY valid JSON, no markdown fences."""


async def evaluate_frame(
    state: ProactiveState,
    api_key: str,
    session_id: str,
    current_step: str,
    recipe_name: Optional[str],
    timer_info: str,
) -> Optional[dict[str, Any]]:
    """Evaluate the latest frame and return structured result or None on failure."""
    if not PASSIVE_EVAL_ENABLED:
        return None

    if not state.latest_frame:
        return None

    frame_age = time.time() - state.latest_frame_at
    if frame_age < MIN_FRAME_AGE_S or frame_age > 15.0:
        return None

    if current_step not in PASSIVE_EVAL_STEPS:
        return None

    prompt = EVAL_PROMPT.format(
        step=current_step,
        recipe=recipe_name or "not set",
        timers=timer_info or "none",
    )

    try:
        import google.genai as genai
        client = genai.Client(api_key=api_key)

        frame_b64 = base64.b64encode(state.latest_frame).decode("utf-8")

        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=PASSIVE_EVAL_MODEL,
                contents=[
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": frame_b64}},
                        ]
                    }
                ],
            ),
            timeout=EVAL_TIMEOUT_S,
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text[:-3].strip()

        result = json.loads(text)
        emit("backend.proactive", "proactive_eval_result",
             session_id=session_id,
             details={"result": result, "frame_age_s": round(frame_age, 1)})
        return result

    except asyncio.TimeoutError:
        emit("backend.proactive", "proactive_eval_timeout",
             session_id=session_id, severity="WARNING")
        return None
    except Exception as e:
        emit("backend.proactive", "proactive_eval_error",
             session_id=session_id, severity="WARNING",
             details={"error": str(e)})
        return None


def process_eval_result(
    result: dict[str, Any],
    state: ProactiveState,
    session_id: str,
) -> None:
    """Convert an evaluator result into a proactive candidate if warranted."""
    action = result.get("action")
    if not action:
        state.eval_persistence.clear()
        return

    urgency_str = result.get("urgency")
    confidence = float(result.get("confidence", 0.0))
    reason = result.get("reason", "")
    reason_code = result.get("reason_code", "unclear")

    if urgency_str == "urgent_now":
        lane = Lane.URGENT_NOW
        min_confidence = 0.7
    elif urgency_str == "important_next_gap":
        lane = Lane.IMPORTANT_NEXT_GAP
        min_confidence = 0.6
    else:
        state.eval_persistence.clear()
        return

    if confidence < min_confidence:
        emit("backend.proactive", "proactive_eval_below_threshold",
             session_id=session_id,
             details={"confidence": confidence, "threshold": min_confidence,
                       "urgency": urgency_str})
        return

    if reason_code in {"normal_activity", "scene_change", "unclear"}:
        emit(
            "backend.proactive",
            "proactive_eval_suppressed_non_issue",
            session_id=session_id,
            details={"reason_code": reason_code, "reason": reason},
        )
        return

    dedupe_key = f"eval_{urgency_str}_{reason_code}"

    if lane != Lane.URGENT_NOW:
        rounds = state.record_eval_persistence(dedupe_key)
        if rounds < PERSISTENCE_ROUNDS:
            emit("backend.proactive", "proactive_eval_persistence_pending",
                 session_id=session_id,
                 details={"dedupe_key": dedupe_key, "rounds": rounds,
                           "required": PERSISTENCE_ROUNDS})
            return

    state.clear_eval_persistence(dedupe_key)

    prompt_text = f"SYSTEM: Visual observation — {action}. Deliver a brief coaching note to the cook."

    create_candidate(
        state,
        lane=lane,
        trigger_source="passive_eval",
        reason_code=reason_code,
        prompt_text=prompt_text,
        dedupe_key=dedupe_key,
        confidence=confidence,
    )


async def passive_eval_loop(
    session_id: str,
    api_key: str,
    get_session: Any,
) -> None:
    """Background loop that runs passive evaluation at regular intervals.

    get_session is a callable that returns the current SessionContext or None.
    """
    if not PASSIVE_EVAL_ENABLED:
        return

    try:
        await asyncio.sleep(5.0)

        while True:
            await asyncio.sleep(PASSIVE_EVAL_INTERVAL)

            session = get_session()
            if session is None or session.ended:
                return

            if session.current_step not in PASSIVE_EVAL_STEPS:
                continue

            timer_parts = []
            for t in session.timers.values():
                rem = t.remaining_seconds
                if rem > 0:
                    timer_parts.append(f"{t.label}: {int(rem)}s left")
            timer_info = "; ".join(timer_parts) if timer_parts else "none"

            result = await evaluate_frame(
                session.proactive,
                api_key=api_key,
                session_id=session_id,
                current_step=session.current_step,
                recipe_name=session.recipe_name,
                timer_info=timer_info,
            )

            if result:
                process_eval_result(result, session.proactive, session_id)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        emit("backend.proactive", "passive_eval_loop_error",
             session_id=session_id, severity="ERROR",
             details={"error": str(e)})
