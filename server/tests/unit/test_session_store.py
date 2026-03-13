"""Unit tests for session store and data models."""

import asyncio
import time
import pytest

from server.session_store import (
    SessionContext,
    TimerRecord,
    get_or_create_session,
    cancel_session_timers,
    cleanup_session_if_idle,
    build_reconnect_primer,
    validate_step_transition,
    new_timer_id,
    VALID_STEPS,
    SESSION_IDLE_TTL,
)
from server.observability import clear_artifact_buffer


@pytest.fixture(autouse=True)
def _clear_obs():
    clear_artifact_buffer()
    yield
    clear_artifact_buffer()


class TestSessionContext:
    def test_new_session_defaults(self):
        ctx = SessionContext(session_id="test1")
        assert ctx.session_id == "test1"
        assert ctx.current_step == "idle"
        assert ctx.monitoring_status == "Waiting for ingredients"
        assert ctx.demo_speed is False
        assert len(ctx.timers) == 0

    def test_touch_updates_last_seen(self):
        ctx = SessionContext(session_id="test1")
        before = ctx.last_seen_at
        time.sleep(0.01)
        ctx.touch()
        assert ctx.last_seen_at > before

    def test_to_state_snapshot(self):
        ctx = SessionContext(session_id="test1", recipe_name="chicken")
        snap = ctx.to_state_snapshot()
        assert snap["type"] == "state_update"
        assert snap["session_id"] == "test1"
        assert snap["recipe_name"] == "chicken"
        assert snap["current_step"] == "idle"
        assert isinstance(snap["timers"], list)
        assert isinstance(snap["transcript"], list)


class TestTimerRecord:
    def test_remaining_seconds(self):
        t = TimerRecord(
            id="tmr_1", label="sear", total_seconds=120,
            effective_seconds=12, started_at=time.time() - 5,
        )
        assert 6 < t.remaining_seconds < 8

    def test_expired_timer(self):
        t = TimerRecord(
            id="tmr_1", label="sear", total_seconds=10,
            effective_seconds=1, started_at=time.time() - 5,
        )
        assert t.remaining_seconds == 0.0

    def test_to_dict(self):
        t = TimerRecord(
            id="tmr_1", label="sear", total_seconds=120,
            effective_seconds=12, started_at=time.time(),
        )
        d = t.to_dict()
        assert d["id"] == "tmr_1"
        assert d["label"] == "sear"
        assert "remaining_seconds" in d


class TestGetOrCreateSession:
    def test_create_new(self):
        store = {}
        ctx = get_or_create_session(store, "s1")
        assert ctx.session_id == "s1"
        assert "s1" in store

    def test_get_existing(self):
        store = {}
        ctx1 = get_or_create_session(store, "s1")
        ctx1.recipe_name = "chicken"
        ctx2 = get_or_create_session(store, "s1")
        assert ctx2.recipe_name == "chicken"
        assert ctx1 is ctx2


class TestCancelTimers:
    @pytest.mark.asyncio
    async def test_cancel_all(self):
        ctx = SessionContext(session_id="s1")

        async def dummy():
            await asyncio.sleep(999)

        task = asyncio.create_task(dummy())
        ctx.timers["t1"] = TimerRecord(
            id="t1", label="x", total_seconds=10,
            effective_seconds=10, started_at=time.time(), task=task,
        )
        cancel_session_timers(ctx)
        await asyncio.sleep(0)  # let cancellation propagate
        assert task.cancelled()


class TestCleanupSession:
    @pytest.mark.asyncio
    async def test_cleanup_idle(self):
        store = {}
        ctx = get_or_create_session(store, "s1")
        ctx.last_seen_at = time.time() - SESSION_IDLE_TTL - 1
        removed = await cleanup_session_if_idle(store, "s1")
        assert removed is True
        assert "s1" not in store

    @pytest.mark.asyncio
    async def test_keep_active(self):
        store = {}
        get_or_create_session(store, "s1")
        removed = await cleanup_session_if_idle(store, "s1")
        assert removed is False
        assert "s1" in store


class TestReconnectPrimer:
    def test_basic_primer(self):
        ctx = SessionContext(session_id="s1", recipe_name="garlic chicken", current_step="sear_side_1")
        primer = build_reconnect_primer(ctx)
        assert "garlic chicken" in primer
        assert "sear_side_1" in primer
        assert "SYSTEM:" in primer

    def test_primer_with_timers(self):
        ctx = SessionContext(session_id="s1", current_step="heat")
        ctx.timers["t1"] = TimerRecord(
            id="t1", label="sear", total_seconds=120,
            effective_seconds=60, started_at=time.time() - 10,
        )
        primer = build_reconnect_primer(ctx)
        assert "sear" in primer
        assert "left" in primer


class TestStepValidation:
    def test_valid_forward(self):
        assert validate_step_transition("idle", "prep") is True
        assert validate_step_transition("prep", "heat") is True
        assert validate_step_transition("heat", "sear_side_1") is True

    def test_same_step(self):
        assert validate_step_transition("heat", "heat") is True

    def test_invalid_backward(self):
        assert validate_step_transition("sear_side_1", "prep") is False

    def test_invalid_step_name(self):
        assert validate_step_transition("idle", "nonexistent") is False

    def test_all_valid_steps(self):
        for step in VALID_STEPS:
            assert validate_step_transition(step, step) is True


class TestNewTimerId:
    def test_unique(self):
        ids = {new_timer_id() for _ in range(100)}
        assert len(ids) == 100

    def test_prefix(self):
        assert new_timer_id().startswith("tmr_")
