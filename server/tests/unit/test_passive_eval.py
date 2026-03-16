"""Unit tests for passive evaluator result processing."""

import pytest

from server.observability import clear_artifact_buffer, get_artifact_buffer
from server.passive_eval import process_eval_result
from server.proactive import Lane, PhaseGate, ProactiveState, PERSISTENCE_ROUNDS


@pytest.fixture(autouse=True)
def _clear_obs():
    clear_artifact_buffer()
    yield
    clear_artifact_buffer()


def _make_state(**kwargs) -> ProactiveState:
    state = ProactiveState(session_id="s1", **kwargs)
    state.phase_gate = PhaseGate.BALANCED_ENABLED
    return state


class TestProcessEvalResult:
    def test_null_action_clears_all_persistence(self):
        state = _make_state()
        state.eval_persistence["some_key"] = 1
        process_eval_result({"action": None}, state, "s1")
        assert len(state.eval_persistence) == 0
        assert len(state.pending_candidates) == 0

    def test_urgent_creates_candidate_immediately(self):
        state = _make_state()
        result = {
            "action": "Food is burning, flip now",
            "urgency": "urgent_now",
            "confidence": 0.9,
            "reason_code": "food_burning",
            "reason": "visible burning on the surface",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 1
        candidate = state.pending_candidates[0]
        assert candidate.lane == Lane.URGENT_NOW
        assert candidate.reason_code == "food_burning"

    def test_unsafe_knife_grip_creates_urgent_candidate(self):
        state = _make_state()
        result = {
            "action": "Pause — curl your fingertips for safety.",
            "urgency": "urgent_now",
            "confidence": 0.85,
            "reason_code": "unsafe_knife_grip",
            "reason": "flat fingers exposed to blade",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 1
        candidate = state.pending_candidates[0]
        assert candidate.lane == Lane.URGENT_NOW
        assert candidate.reason_code == "unsafe_knife_grip"

    def test_important_requires_persistence(self):
        state = _make_state()
        result = {
            "action": "Pan appears cold, wait for shimmer",
            "urgency": "important_next_gap",
            "confidence": 0.8,
            "reason_code": "pan_cold_with_food",
            "reason": "chicken appears to be in oil without heat shimmer",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 0

        for _ in range(PERSISTENCE_ROUNDS - 1):
            process_eval_result(result, state, "s1")

        assert len(state.pending_candidates) == 1
        candidate = state.pending_candidates[0]
        assert candidate.lane == Lane.IMPORTANT_NEXT_GAP
        assert candidate.reason_code == "pan_cold_with_food"

    def test_below_confidence_threshold_skipped(self):
        state = _make_state()
        result = {
            "action": "Maybe too hot?",
            "urgency": "urgent_now",
            "confidence": 0.3,
            "reason_code": "dangerous_heat",
            "reason": "uncertain heat level",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 0
        events = [
            e for e in get_artifact_buffer()
            if e["event_type"] == "proactive_eval_below_threshold"
        ]
        assert len(events) == 1

    def test_unknown_urgency_ignored(self):
        state = _make_state()
        result = {
            "action": "looks good",
            "urgency": "low",
            "confidence": 0.9,
            "reason_code": "unclear",
            "reason": "nice browning",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 0

    def test_normal_activity_reason_code_is_suppressed(self):
        state = _make_state()
        result = {
            "action": "Keep going",
            "urgency": "important_next_gap",
            "confidence": 0.95,
            "reason_code": "normal_activity",
            "reason": "person is chopping ingredients normally",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 0
        events = [
            e for e in get_artifact_buffer()
            if e["event_type"] == "proactive_eval_suppressed_non_issue"
        ]
        assert len(events) == 1

    def test_scene_change_reason_code_is_suppressed(self):
        state = _make_state()
        result = {
            "action": "Camera moved",
            "urgency": "important_next_gap",
            "confidence": 0.95,
            "reason_code": "scene_change",
            "reason": "camera repositioned toward the counter",
        }
        process_eval_result(result, state, "s1")
        assert len(state.pending_candidates) == 0

    def test_dedupe_uses_reason_code_not_free_text(self):
        state = _make_state()
        result1 = {
            "action": "Pan appears cold",
            "urgency": "important_next_gap",
            "confidence": 0.8,
            "reason_code": "pan_cold_with_food",
            "reason": "oil is static and food is in the pan",
        }
        result2 = {
            "action": "Wait a bit longer for shimmer",
            "urgency": "important_next_gap",
            "confidence": 0.82,
            "reason_code": "pan_cold_with_food",
            "reason": "surface still looks cool before browning starts",
        }
        process_eval_result(result1, state, "s1")
        process_eval_result(result2, state, "s1")
        assert len(state.pending_candidates) == 1
