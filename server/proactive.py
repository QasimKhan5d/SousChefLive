"""Proactive coordinator for SousChef Live.

Manages proactive candidate creation, lifecycle, phase gating,
quiet-gap detection, and dispatch. ALL server-originated proactive
speech must flow through the ProactiveDispatcher — no other code path
is allowed to write directly to text_input_queue for proactive purposes.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

from server.observability import emit

PROACTIVE_ENABLED = os.getenv("PROACTIVE_ENABLED", "true").lower() == "true"
PASSIVE_EVAL_ENABLED = os.getenv("PASSIVE_EVAL_ENABLED", "true").lower() == "true"
PASSIVE_EVAL_INTERVAL = int(os.getenv("PASSIVE_EVAL_INTERVAL", "12"))
PASSIVE_EVAL_MODEL = os.getenv("PASSIVE_EVAL_MODEL", "gemini-2.0-flash-lite")

QUIET_GAP_MS = 700
URGENT_COOLDOWN_S = 10.0
IMPORTANT_COOLDOWN_S = 45.0
NON_URGENT_CANDIDATE_TTL_S = 20.0
POST_INTERRUPT_SUPPRESSION_S = 5.0
PHASE_STABILITY_S = 10.0
STEP_GRACE_WINDOW_S = 12.0
PERSISTENCE_ROUNDS = 2


class Lane(str, Enum):
    URGENT_NOW = "urgent_now"
    IMPORTANT_NEXT_GAP = "important_next_gap"
    MILESTONE_NUDGE = "milestone_nudge"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"


class PhaseGate(str, Enum):
    URGENT_ONLY = "urgent_only"
    BALANCED_ENABLED = "balanced_enabled"


# `prep` is intentionally treated as low-commitment for non-urgent nudges.
# Knife work still receives strict urgent monitoring via the urgent lane.
LOW_COMMITMENT_STEPS = {"idle", "prep"}
NON_URGENT_ACTIVE_STEPS = {
    "heat",
    "sear_side_1",
    "flip",
    "sear_side_2",
    "baste",
    "rest",
    "done",
}
PASSIVE_EVAL_STEPS = LOW_COMMITMENT_STEPS | NON_URGENT_ACTIVE_STEPS


@dataclass
class ProactiveCandidate:
    candidate_id: str = field(default_factory=lambda: f"pc_{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    lane: Lane = Lane.MILESTONE_NUDGE
    trigger_source: str = ""
    reason_code: str = ""
    prompt_text: str = ""
    dedupe_key: str = ""
    confidence: float = 1.0
    connection_epoch: int = 0
    step_version: int = 0
    created_at: float = field(default_factory=time.time)
    status: CandidateStatus = CandidateStatus.PENDING
    terminal_reason: str = ""
    released_by: str = ""
    allow_during_urgent_only: bool = False
    ignore_step_grace: bool = False
    ttl_s: Optional[float] = None

    @property
    def age_ms(self) -> float:
        return (time.time() - self.created_at) * 1000


@dataclass
class ProactiveState:
    """Per-session state for the proactive coordinator."""

    session_id: str = ""
    current_step: str = "idle"
    connection_epoch: int = 0
    step_version: int = 0
    phase_gate: PhaseGate = PhaseGate.URGENT_ONLY

    model_generating: bool = False
    user_speaking: bool = False
    last_model_audio_at: float = 0.0
    last_turn_complete_at: float = 0.0
    last_interrupted_at: float = 0.0
    last_input_transcription_at: float = 0.0

    last_step_change_at: float = 0.0
    last_recipe_set_at: float = 0.0
    last_timer_started_at: float = 0.0
    phase_stable_since: float = 0.0

    latest_frame: Optional[bytes] = None
    latest_frame_at: float = 0.0

    pending_candidates: list[ProactiveCandidate] = field(default_factory=list)
    candidate_history: list[ProactiveCandidate] = field(default_factory=list)

    last_proactive_sent_at: float = 0.0
    sent_milestone_keys: set[str] = field(default_factory=set)
    dedupe_cooldowns: dict[str, float] = field(default_factory=dict)
    eval_persistence: dict[str, int] = field(default_factory=dict)

    def increment_epoch(self) -> int:
        self.connection_epoch += 1
        return self.connection_epoch

    def increment_step_version(self, step_name: str | None = None) -> int:
        self.step_version += 1
        self.last_step_change_at = time.time()
        self.phase_stable_since = time.time()
        if step_name:
            self.current_step = step_name
        self._invalidate_non_urgent_by_step()
        return self.step_version

    def mark_recipe_selected(self) -> None:
        self.last_recipe_set_at = time.time()

    def mark_timer_started(self) -> None:
        self.last_timer_started_at = time.time()

    def update_phase_gate(self, current_step: str, has_recipe: bool, has_timer: bool) -> PhaseGate:
        self.current_step = current_step
        if current_step in LOW_COMMITMENT_STEPS:
            self.phase_gate = PhaseGate.URGENT_ONLY
            return self.phase_gate

        if has_recipe and (current_step in NON_URGENT_ACTIVE_STEPS or has_timer):
            elapsed = time.time() - self.phase_stable_since
            self.phase_gate = (
                PhaseGate.BALANCED_ENABLED
                if elapsed >= PHASE_STABILITY_S
                else PhaseGate.URGENT_ONLY
            )
            return self.phase_gate

        self.phase_gate = PhaseGate.URGENT_ONLY
        return self.phase_gate

    def record_model_audio(self) -> None:
        self.model_generating = True
        self.last_model_audio_at = time.time()

    def record_turn_complete(self) -> None:
        self.model_generating = False
        self.user_speaking = False
        self.last_turn_complete_at = time.time()

    def record_interrupted(self) -> None:
        self.model_generating = False
        self.last_interrupted_at = time.time()
        self._suppress_non_urgent("post_interrupt")

    def record_input_transcription(self) -> None:
        self.user_speaking = True
        self.last_input_transcription_at = time.time()

    def refresh_activity_flags(self) -> None:
        now = time.time()
        if self.user_speaking and self.last_input_transcription_at > 0:
            if now - self.last_input_transcription_at > QUIET_GAP_MS / 1000.0:
                self.user_speaking = False

    def quiet_gap_ms(self) -> float:
        now = time.time()
        reference = max(self.last_turn_complete_at, self.last_input_transcription_at)
        if reference <= 0:
            return 0.0
        return max(0.0, (now - reference) * 1000.0)

    def in_step_grace_window(self) -> bool:
        if self.last_step_change_at <= 0:
            return False
        return (time.time() - self.last_step_change_at) < STEP_GRACE_WINDOW_S

    def is_quiet_gap_ready(self) -> bool:
        self.refresh_activity_flags()
        if self.model_generating or self.user_speaking:
            return False
        if self.last_turn_complete_at <= 0:
            return False
        return self.quiet_gap_ms() >= QUIET_GAP_MS

    def can_send_non_urgent(self, candidate: Optional[ProactiveCandidate] = None) -> bool:
        self.refresh_activity_flags()
        if self.phase_gate == PhaseGate.URGENT_ONLY and not (candidate and candidate.allow_during_urgent_only):
            return False
        if self.model_generating or self.user_speaking:
            return False
        if not (candidate and candidate.ignore_step_grace) and self.in_step_grace_window():
            return False
        if time.time() - self.last_interrupted_at < POST_INTERRUPT_SUPPRESSION_S:
            return False
        return self.is_quiet_gap_ready()

    def cooldown_ms_remaining(self, dedupe_key: str, lane: Lane) -> float:
        if not dedupe_key or lane == Lane.MILESTONE_NUDGE:
            return 0.0
        now = time.time()
        last_sent = self.dedupe_cooldowns.get(dedupe_key, 0.0)
        cooldown = URGENT_COOLDOWN_S if lane == Lane.URGENT_NOW else IMPORTANT_COOLDOWN_S
        remaining = max(0.0, cooldown - (now - last_sent))
        return remaining * 1000.0

    def _invalidate_non_urgent_by_step(self) -> None:
        for candidate in self.pending_candidates:
            if candidate.lane != Lane.URGENT_NOW and candidate.status == CandidateStatus.PENDING:
                candidate.status = CandidateStatus.EXPIRED
                candidate.terminal_reason = "step_version_changed"
                _emit_candidate_event("proactive_candidate_expired", candidate, self)

    def _suppress_non_urgent(self, reason: str) -> None:
        for candidate in self.pending_candidates:
            if candidate.lane != Lane.URGENT_NOW and candidate.status == CandidateStatus.PENDING:
                candidate.status = CandidateStatus.SUPPRESSED
                candidate.terminal_reason = reason
                _emit_candidate_event("proactive_candidate_suppressed", candidate, self)

    def check_dedupe(self, dedupe_key: str, lane: Lane) -> bool:
        if not dedupe_key:
            return True
        if lane == Lane.MILESTONE_NUDGE:
            return dedupe_key not in self.sent_milestone_keys
        now = time.time()
        last_sent = self.dedupe_cooldowns.get(dedupe_key, 0.0)
        cooldown = URGENT_COOLDOWN_S if lane == Lane.URGENT_NOW else IMPORTANT_COOLDOWN_S
        return (now - last_sent) >= cooldown

    def record_send(self, candidate: ProactiveCandidate) -> None:
        self.last_proactive_sent_at = time.time()
        if candidate.dedupe_key:
            if candidate.lane == Lane.MILESTONE_NUDGE:
                self.sent_milestone_keys.add(candidate.dedupe_key)
            else:
                self.dedupe_cooldowns[candidate.dedupe_key] = time.time()

    def record_eval_persistence(self, key: str) -> int:
        self.eval_persistence[key] = self.eval_persistence.get(key, 0) + 1
        return self.eval_persistence[key]

    def clear_eval_persistence(self, key: str | None = None) -> None:
        if key is None:
            self.eval_persistence.clear()
            return
        self.eval_persistence.pop(key, None)

    def finalize_candidates(self) -> None:
        now = time.time()
        still_pending = []
        for candidate in self.pending_candidates:
            if candidate.status != CandidateStatus.PENDING:
                self.candidate_history.append(candidate)
                continue
            if candidate.connection_epoch != self.connection_epoch:
                candidate.status = CandidateStatus.EXPIRED
                candidate.terminal_reason = "stale_epoch"
                _emit_candidate_event("proactive_candidate_expired", candidate, self)
                self.candidate_history.append(candidate)
                continue
            if candidate.lane != Lane.URGENT_NOW and candidate.step_version != self.step_version:
                candidate.status = CandidateStatus.EXPIRED
                candidate.terminal_reason = "step_version_changed"
                _emit_candidate_event("proactive_candidate_expired", candidate, self)
                self.candidate_history.append(candidate)
                continue
            ttl_s = candidate.ttl_s if candidate.ttl_s is not None else NON_URGENT_CANDIDATE_TTL_S
            if candidate.lane != Lane.URGENT_NOW and (now - candidate.created_at) > ttl_s:
                candidate.status = CandidateStatus.EXPIRED
                candidate.terminal_reason = "ttl_expired"
                _emit_candidate_event("proactive_candidate_expired", candidate, self)
                self.candidate_history.append(candidate)
                continue
            still_pending.append(candidate)
        self.pending_candidates = still_pending
        if len(self.candidate_history) > 300:
            self.candidate_history = self.candidate_history[-150:]


class ProactiveDispatcher:
    """Single entry point for all proactive speech dispatch."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._queue: asyncio.Queue | None = None
        self._event_sender: Optional[Callable[[dict], Awaitable[None]]] = None
        self._lock = asyncio.Lock()

    def rebind(
        self,
        queue: asyncio.Queue,
        event_sender: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> None:
        self._queue = queue
        self._event_sender = event_sender

    async def dispatch(self, candidate: ProactiveCandidate, state: ProactiveState) -> bool:
        async with self._lock:
            if candidate.status != CandidateStatus.PENDING:
                return False

            if candidate.connection_epoch != state.connection_epoch:
                candidate.status = CandidateStatus.EXPIRED
                candidate.terminal_reason = "stale_epoch"
                _emit_candidate_event("proactive_candidate_expired", candidate, state)
                return False

            if not state.check_dedupe(candidate.dedupe_key, candidate.lane):
                candidate.status = CandidateStatus.SUPPRESSED
                candidate.terminal_reason = "dedupe"
                _emit_candidate_event("proactive_candidate_suppressed", candidate, state)
                return False

            if candidate.lane == Lane.URGENT_NOW:
                return await self._send(candidate, state, released_by="immediate")

            if not state.can_send_non_urgent(candidate):
                return False

            return await self._send(candidate, state, released_by="quiet_gap")

    async def try_release_pending(self, state: ProactiveState) -> None:
        state.finalize_candidates()

        urgent = [
            candidate for candidate in state.pending_candidates
            if candidate.lane == Lane.URGENT_NOW and candidate.status == CandidateStatus.PENDING
        ]
        for candidate in urgent:
            await self.dispatch(candidate, state)

        non_urgent = [
            candidate for candidate in state.pending_candidates
            if candidate.lane != Lane.URGENT_NOW and candidate.status == CandidateStatus.PENDING
        ]
        for candidate in non_urgent:
            sent = await self.dispatch(candidate, state)
            if sent:
                break

    async def _send(self, candidate: ProactiveCandidate, state: ProactiveState, released_by: str) -> bool:
        if not self._queue:
            candidate.status = CandidateStatus.SUPPRESSED
            candidate.terminal_reason = "no_queue"
            _emit_candidate_event("proactive_candidate_suppressed", candidate, state)
            return False

        try:
            await self._queue.put(candidate.prompt_text)
        except asyncio.QueueFull:
            candidate.status = CandidateStatus.SUPPRESSED
            candidate.terminal_reason = "queue_full"
            _emit_candidate_event("proactive_candidate_suppressed", candidate, state)
            return False

        candidate.status = CandidateStatus.SENT
        candidate.released_by = released_by
        state.record_send(candidate)

        if self._event_sender:
            try:
                await self._event_sender({
                    "type": "proactive_meta",
                    "candidate_id": candidate.candidate_id,
                    "lane": candidate.lane.value,
                    "trigger_source": candidate.trigger_source,
                    "reason_code": candidate.reason_code,
                })
            except Exception:
                pass

        _emit_candidate_event("proactive_candidate_sent", candidate, state)
        return True


def create_candidate(
    state: ProactiveState,
    lane: Lane,
    trigger_source: str,
    reason_code: str,
    prompt_text: str,
    dedupe_key: str = "",
    confidence: float = 1.0,
    *,
    allow_during_urgent_only: bool = False,
    ignore_step_grace: bool = False,
    ttl_s: Optional[float] = None,
) -> ProactiveCandidate | None:
    if not PROACTIVE_ENABLED:
        return None

    candidate = ProactiveCandidate(
        session_id=state.session_id,
        lane=lane,
        trigger_source=trigger_source,
        reason_code=reason_code,
        prompt_text=prompt_text,
        dedupe_key=dedupe_key,
        confidence=confidence,
        connection_epoch=state.connection_epoch,
        step_version=state.step_version,
        allow_during_urgent_only=allow_during_urgent_only,
        ignore_step_grace=ignore_step_grace,
        ttl_s=ttl_s,
    )

    if lane != Lane.URGENT_NOW and state.phase_gate == PhaseGate.URGENT_ONLY and not allow_during_urgent_only:
        candidate.status = CandidateStatus.SUPPRESSED
        candidate.terminal_reason = "phase_gate_urgent_only"
        state.candidate_history.append(candidate)
        _emit_candidate_event("proactive_candidate_suppressed", candidate, state)
        return None

    if not state.check_dedupe(dedupe_key, lane):
        candidate.status = CandidateStatus.SUPPRESSED
        candidate.terminal_reason = "dedupe"
        state.candidate_history.append(candidate)
        emit(
            "backend.proactive",
            "proactive_cooldown_active",
            session_id=state.session_id,
            details={
                "candidate_id": candidate.candidate_id,
                "dedupe_key": dedupe_key,
                "lane": lane.value,
                "cooldown_ms_remaining": round(state.cooldown_ms_remaining(dedupe_key, lane), 1),
            },
        )
        _emit_candidate_event("proactive_candidate_suppressed", candidate, state)
        return None

    state.pending_candidates.append(candidate)
    _emit_candidate_event("proactive_candidate_created", candidate, state)
    return candidate


def _emit_candidate_event(event_type: str, candidate: ProactiveCandidate, state: ProactiveState) -> dict:
    return emit(
        "backend.proactive",
        event_type,
        session_id=state.session_id or candidate.session_id,
        details={
            "candidate_id": candidate.candidate_id,
            "lane": candidate.lane.value,
            "trigger_source": candidate.trigger_source,
            "reason_code": candidate.reason_code,
            "dedupe_key": candidate.dedupe_key,
            "session_step": state.current_step,
            "step_version": candidate.step_version,
            "connection_epoch": candidate.connection_epoch,
            "confidence": candidate.confidence,
            "candidate_age_ms": round(candidate.age_ms, 1),
            "status": candidate.status.value,
            "terminal_reason": candidate.terminal_reason,
            "released_by": candidate.released_by,
            "quiet_gap_ms": round(state.quiet_gap_ms(), 1),
            "user_speaking": state.user_speaking,
            "model_generating": state.model_generating,
            "phase_gate": state.phase_gate.value,
            "cooldown_ms_remaining": round(state.cooldown_ms_remaining(candidate.dedupe_key, candidate.lane), 1),
        },
    )
