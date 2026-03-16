"""Unit tests for the proactive coordinator, dispatcher, and guardrails."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from server.observability import clear_artifact_buffer, get_artifact_buffer
from server.proactive import (
    IMPORTANT_COOLDOWN_S,
    NON_URGENT_CANDIDATE_TTL_S,
    PHASE_STABILITY_S,
    POST_INTERRUPT_SUPPRESSION_S,
    PERSISTENCE_ROUNDS,
    STEP_GRACE_WINDOW_S,
    URGENT_COOLDOWN_S,
    CandidateStatus,
    Lane,
    PhaseGate,
    ProactiveDispatcher,
    ProactiveState,
    create_candidate,
)


@pytest.fixture(autouse=True)
def _clear_obs():
    clear_artifact_buffer()
    yield
    clear_artifact_buffer()


def _make_state(**kwargs) -> ProactiveState:
    state = ProactiveState(session_id="test_session", **kwargs)
    return state


def _ready_non_urgent_state(**kwargs) -> ProactiveState:
    state = _make_state(**kwargs)
    state.phase_gate = PhaseGate.BALANCED_ENABLED
    state.last_turn_complete_at = time.time() - 2.0
    state.last_input_transcription_at = time.time() - 2.0
    state.last_step_change_at = time.time() - STEP_GRACE_WINDOW_S - 1
    state.last_interrupted_at = 0.0
    return state


class TestCandidateLifecycle:
    def test_new_candidate_is_pending(self):
        state = _ready_non_urgent_state()
        candidate = create_candidate(
            state, Lane.MILESTONE_NUDGE, "timer", "test", "msg", dedupe_key="k1"
        )
        assert candidate is not None
        assert candidate.status == CandidateStatus.PENDING

    def test_finalize_expires_stale_epoch(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        candidate = create_candidate(
            state, Lane.MILESTONE_NUDGE, "timer", "test", "msg", dedupe_key="k1"
        )
        state.connection_epoch = 2
        state.finalize_candidates()
        assert candidate.status == CandidateStatus.EXPIRED
        assert candidate.terminal_reason == "stale_epoch"

    def test_finalize_expires_stale_step_version(self):
        state = _ready_non_urgent_state(step_version=1)
        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "test", "msg", dedupe_key="k1"
        )
        state.step_version = 2
        state.finalize_candidates()
        assert candidate.status == CandidateStatus.EXPIRED
        assert candidate.terminal_reason == "step_version_changed"

    def test_urgent_not_expired_by_step_version(self):
        state = _ready_non_urgent_state(step_version=1)
        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1"
        )
        state.step_version = 2
        state.finalize_candidates()
        assert candidate.status == CandidateStatus.PENDING

    def test_finalize_expires_ttl(self):
        state = _ready_non_urgent_state()
        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "test", "msg", dedupe_key="k1"
        )
        candidate.created_at = time.time() - NON_URGENT_CANDIDATE_TTL_S - 1
        state.finalize_candidates()
        assert candidate.status == CandidateStatus.EXPIRED
        assert candidate.terminal_reason == "ttl_expired"

    def test_terminal_candidates_enter_history_once(self):
        state = _ready_non_urgent_state()
        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "test", "msg", dedupe_key="k1"
        )
        state.record_interrupted()
        state.finalize_candidates()
        matches = [c for c in state.candidate_history if c.candidate_id == candidate.candidate_id]
        assert len(matches) == 1
        assert matches[0].status == CandidateStatus.SUPPRESSED


class TestPhaseGating:
    def test_idle_no_recipe_is_urgent_only(self):
        state = _make_state()
        gate = state.update_phase_gate("idle", has_recipe=False, has_timer=False)
        assert gate == PhaseGate.URGENT_ONLY

    def test_prep_is_urgent_only_even_with_recipe(self):
        state = _make_state()
        gate = state.update_phase_gate("prep", has_recipe=True, has_timer=False)
        assert gate == PhaseGate.URGENT_ONLY

    def test_prep_is_still_urgent_only_even_with_timer(self):
        state = _make_state()
        gate = state.update_phase_gate("prep", has_recipe=True, has_timer=True)
        assert gate == PhaseGate.URGENT_ONLY

    def test_heat_after_stability_is_balanced_enabled(self):
        state = _make_state()
        state.phase_stable_since = time.time() - PHASE_STABILITY_S - 1
        gate = state.update_phase_gate("heat", has_recipe=True, has_timer=False)
        assert gate == PhaseGate.BALANCED_ENABLED

    def test_heat_before_stability_is_urgent_only(self):
        state = _make_state()
        state.phase_stable_since = time.time()
        gate = state.update_phase_gate("heat", has_recipe=True, has_timer=False)
        assert gate == PhaseGate.URGENT_ONLY

    def test_non_urgent_blocked_in_urgent_only_phase(self):
        state = _make_state()
        state.phase_gate = PhaseGate.URGENT_ONLY
        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "test", "msg", dedupe_key="k1"
        )
        assert candidate is None

    def test_urgent_allowed_in_urgent_only_phase(self):
        state = _make_state()
        state.phase_gate = PhaseGate.URGENT_ONLY
        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1"
        )
        assert candidate is not None

    def test_milestone_can_be_created_in_urgent_only_when_allowed(self):
        state = _make_state()
        state.phase_gate = PhaseGate.URGENT_ONLY
        candidate = create_candidate(
            state,
            Lane.MILESTONE_NUDGE,
            "step_change",
            "step_entered_heat",
            "msg",
            dedupe_key="step_heat",
            allow_during_urgent_only=True,
        )
        assert candidate is not None
        assert candidate.status == CandidateStatus.PENDING


class TestGraceWindow:
    def test_in_grace_window(self):
        state = _make_state()
        state.last_step_change_at = time.time()
        assert state.in_step_grace_window() is True

    def test_after_grace_window(self):
        state = _make_state()
        state.last_step_change_at = time.time() - STEP_GRACE_WINDOW_S - 1
        assert state.in_step_grace_window() is False

    def test_non_urgent_blocked_during_grace_window(self):
        state = _ready_non_urgent_state()
        state.last_step_change_at = time.time()
        assert state.can_send_non_urgent() is False

    def test_non_urgent_can_ignore_grace_when_explicitly_allowed(self):
        state = _ready_non_urgent_state()
        state.last_step_change_at = time.time()
        candidate = create_candidate(
            state,
            Lane.MILESTONE_NUDGE,
            "timer",
            "timer_expired",
            "msg",
            dedupe_key="timer_1",
            allow_during_urgent_only=True,
            ignore_step_grace=True,
        )
        assert state.can_send_non_urgent(candidate) is True


class TestCooldownAndDedupe:
    def test_milestone_dedupe_once_per_key(self):
        state = _ready_non_urgent_state()
        candidate = create_candidate(
            state, Lane.MILESTONE_NUDGE, "timer", "t", "m", dedupe_key="timer_1"
        )
        assert candidate is not None
        candidate.status = CandidateStatus.SENT
        state.record_send(candidate)
        second = create_candidate(
            state, Lane.MILESTONE_NUDGE, "timer", "t", "m", dedupe_key="timer_1"
        )
        assert second is None

    def test_urgent_cooldown(self):
        state = _ready_non_urgent_state()
        state.dedupe_cooldowns["smoke"] = time.time()
        assert state.check_dedupe("smoke", Lane.URGENT_NOW) is False

    def test_urgent_cooldown_expired(self):
        state = _ready_non_urgent_state()
        state.dedupe_cooldowns["smoke"] = time.time() - URGENT_COOLDOWN_S - 1
        assert state.check_dedupe("smoke", Lane.URGENT_NOW) is True

    def test_important_cooldown_expired(self):
        state = _ready_non_urgent_state()
        state.dedupe_cooldowns["cold_pan"] = time.time() - IMPORTANT_COOLDOWN_S - 1
        assert state.check_dedupe("cold_pan", Lane.IMPORTANT_NEXT_GAP) is True


class TestInterruptSuppression:
    def test_interrupt_suppresses_non_urgent(self):
        state = _ready_non_urgent_state()
        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "test", "msg", dedupe_key="k1"
        )
        state.record_interrupted()
        assert candidate.status == CandidateStatus.SUPPRESSED

    def test_post_interrupt_blocks_send(self):
        state = _ready_non_urgent_state()
        state.last_interrupted_at = time.time()
        assert state.can_send_non_urgent() is False

    def test_post_interrupt_window_passes(self):
        state = _ready_non_urgent_state()
        state.last_interrupted_at = time.time() - POST_INTERRUPT_SUPPRESSION_S - 1
        assert state.can_send_non_urgent() is True


class TestModelGenerating:
    def test_model_generating_blocks_non_urgent(self):
        state = _ready_non_urgent_state()
        state.model_generating = True
        assert state.can_send_non_urgent() is False

    def test_turn_complete_clears_model_generating(self):
        state = _make_state()
        state.model_generating = True
        state.record_turn_complete()
        assert state.model_generating is False

    def test_quiet_gap_requires_model_idle(self):
        state = _ready_non_urgent_state()
        state.model_generating = True
        assert state.is_quiet_gap_ready() is False


class TestQuietGap:
    def test_quiet_gap_after_turn_complete(self):
        state = _ready_non_urgent_state()
        assert state.is_quiet_gap_ready() is True
        assert state.quiet_gap_ms() > 0

    def test_no_quiet_gap_when_user_speaking(self):
        state = _ready_non_urgent_state()
        state.user_speaking = True
        state.last_input_transcription_at = time.time()
        assert state.is_quiet_gap_ready() is False

    def test_no_quiet_gap_without_turn_complete(self):
        state = _make_state()
        state.last_input_transcription_at = time.time() - 2.0
        assert state.is_quiet_gap_ready() is False


class TestPersistence:
    def test_persistence_below_threshold(self):
        state = _make_state()
        count = state.record_eval_persistence("k1")
        assert count == 1
        assert count < PERSISTENCE_ROUNDS

    def test_persistence_meets_threshold(self):
        state = _make_state()
        for _ in range(PERSISTENCE_ROUNDS):
            count = state.record_eval_persistence("k1")
        assert count >= PERSISTENCE_ROUNDS

    def test_clear_specific_persistence(self):
        state = _make_state()
        state.record_eval_persistence("k1")
        state.clear_eval_persistence("k1")
        assert "k1" not in state.eval_persistence

    def test_clear_all_persistence(self):
        state = _make_state()
        state.record_eval_persistence("k1")
        state.record_eval_persistence("k2")
        state.clear_eval_persistence()
        assert state.eval_persistence == {}


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_urgent_dispatches_immediately(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        queue = asyncio.Queue(maxsize=20)
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue)

        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "SYSTEM: smoke!", dedupe_key="k1"
        )
        sent = await dispatcher.dispatch(candidate, state)
        assert sent is True
        assert candidate.status == CandidateStatus.SENT
        assert candidate.released_by == "immediate"
        assert await queue.get() == "SYSTEM: smoke!"

    @pytest.mark.asyncio
    async def test_non_urgent_waits_for_quiet_gap(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        state.model_generating = True
        queue = asyncio.Queue(maxsize=20)
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue)

        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "cold_pan", "SYSTEM: cold pan", dedupe_key="k1"
        )
        sent = await dispatcher.dispatch(candidate, state)
        assert sent is False
        assert candidate.status == CandidateStatus.PENDING

    @pytest.mark.asyncio
    async def test_non_urgent_sends_after_quiet_gap(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        queue = asyncio.Queue(maxsize=20)
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue)

        candidate = create_candidate(
            state, Lane.IMPORTANT_NEXT_GAP, "eval", "cold_pan", "SYSTEM: cold pan", dedupe_key="k1"
        )
        sent = await dispatcher.dispatch(candidate, state)
        assert sent is True
        assert candidate.status == CandidateStatus.SENT
        assert candidate.released_by == "quiet_gap"

    @pytest.mark.asyncio
    async def test_stale_epoch_dropped(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        queue = asyncio.Queue(maxsize=20)
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue)

        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1"
        )
        state.connection_epoch = 2
        sent = await dispatcher.dispatch(candidate, state)
        assert sent is False
        assert candidate.status == CandidateStatus.EXPIRED
        assert candidate.terminal_reason == "stale_epoch"

    @pytest.mark.asyncio
    async def test_try_release_urgent_first(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        queue = asyncio.Queue(maxsize=20)
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue)

        _ = create_candidate(
            state, Lane.MILESTONE_NUDGE, "timer", "t", "non-urgent", dedupe_key="k1"
        )
        urgent = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "urgent!", dedupe_key="k2"
        )
        await dispatcher.try_release_pending(state)
        assert urgent.status == CandidateStatus.SENT
        assert await queue.get() == "urgent!"

    @pytest.mark.asyncio
    async def test_no_queue_suppresses(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        dispatcher = ProactiveDispatcher("test")
        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1"
        )
        sent = await dispatcher.dispatch(candidate, state)
        assert sent is False
        assert candidate.status == CandidateStatus.SUPPRESSED
        assert candidate.terminal_reason == "no_queue"

    @pytest.mark.asyncio
    async def test_event_sender_emits_proactive_meta(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        queue = asyncio.Queue(maxsize=20)
        event_sender = AsyncMock()
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue, event_sender)

        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1"
        )
        await dispatcher.dispatch(candidate, state)
        event_sender.assert_awaited()
        sent_event = event_sender.await_args.args[0]
        assert sent_event["type"] == "proactive_meta"
        assert sent_event["candidate_id"] == candidate.candidate_id


class TestObservabilityEvents:
    def test_candidate_created_emits_session_correlated_event(self):
        state = _ready_non_urgent_state()
        create_candidate(state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1")
        events = [e for e in get_artifact_buffer() if e["event_type"] == "proactive_candidate_created"]
        assert len(events) == 1
        assert events[0]["session_id"] == "test_session"
        assert events[0]["details"]["lane"] == "urgent_now"

    @pytest.mark.asyncio
    async def test_sent_emits_quiet_gap_and_session_step(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        state.current_step = "heat"
        queue = asyncio.Queue(maxsize=20)
        dispatcher = ProactiveDispatcher("test")
        dispatcher.rebind(queue)
        candidate = create_candidate(
            state, Lane.URGENT_NOW, "eval", "smoke", "msg", dedupe_key="k1"
        )
        await dispatcher.dispatch(candidate, state)
        events = [e for e in get_artifact_buffer() if e["event_type"] == "proactive_candidate_sent"]
        assert len(events) == 1
        assert events[0]["session_id"] == "test_session"
        assert "quiet_gap_ms" in events[0]["details"]
        assert events[0]["details"]["session_step"] == "heat"

    def test_phase_gate_suppression_emits_terminal_reason(self):
        state = _make_state()
        state.phase_gate = PhaseGate.URGENT_ONLY
        create_candidate(state, Lane.IMPORTANT_NEXT_GAP, "eval", "cold_pan", "msg", dedupe_key="k1")
        events = [e for e in get_artifact_buffer() if e["event_type"] == "proactive_candidate_suppressed"]
        assert len(events) == 1
        assert events[0]["details"]["terminal_reason"] == "phase_gate_urgent_only"

    def test_interrupt_suppression_emits_event(self):
        state = _ready_non_urgent_state()
        create_candidate(state, Lane.IMPORTANT_NEXT_GAP, "eval", "cold_pan", "msg", dedupe_key="k1")
        state.record_interrupted()
        events = [e for e in get_artifact_buffer() if e["event_type"] == "proactive_candidate_suppressed"]
        assert any(event["details"]["terminal_reason"] == "post_interrupt" for event in events)

    def test_finalize_stale_epoch_emits_event(self):
        state = _ready_non_urgent_state(connection_epoch=1)
        create_candidate(state, Lane.IMPORTANT_NEXT_GAP, "eval", "cold_pan", "msg", dedupe_key="k1")
        state.connection_epoch = 2
        state.finalize_candidates()
        events = [e for e in get_artifact_buffer() if e["event_type"] == "proactive_candidate_expired"]
        assert any(event["details"]["terminal_reason"] == "stale_epoch" for event in events)
