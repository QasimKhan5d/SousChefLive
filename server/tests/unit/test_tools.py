"""Unit tests for tool implementations."""

import asyncio
import pytest

from server.session_store import SessionContext
from server.tools import set_timer, update_cooking_step, get_cooking_state, update_recipe
from server.observability import clear_artifact_buffer


@pytest.fixture(autouse=True)
def _clear_obs():
    clear_artifact_buffer()
    yield
    clear_artifact_buffer()


@pytest.fixture
def session():
    return SessionContext(session_id="test_session")


@pytest.fixture
def text_queue():
    return asyncio.Queue()


@pytest.fixture
def events():
    captured = []

    async def send_event(event):
        captured.append(event)

    return captured, send_event


class TestSetTimer:
    @pytest.mark.asyncio
    async def test_basic_timer(self, session, text_queue, events):
        captured, send_event = events
        result = await set_timer(
            120, "sear_side_1",
            session=session, text_input_queue=text_queue, send_event=send_event,
        )
        assert "timer_id" in result
        assert result["label"] == "sear_side_1"
        assert result["effective_seconds"] == 120
        assert result["timer_id"] in session.timers
        assert len(captured) == 1
        assert captured[0]["type"] == "state_update"

        # Cleanup task
        session.timers[result["timer_id"]].task.cancel()

    @pytest.mark.asyncio
    async def test_demo_speed(self, session, text_queue, events):
        captured, send_event = events
        session.demo_speed = True
        result = await set_timer(
            120, "sear",
            session=session, text_input_queue=text_queue, send_event=send_event,
        )
        assert result["effective_seconds"] == 12
        session.timers[result["timer_id"]].task.cancel()

    @pytest.mark.asyncio
    async def test_timer_alerts_create_candidates(self, session, text_queue, events):
        captured, send_event = events
        session.demo_speed = True
        result = await set_timer(
            10, "quick",
            session=session, text_input_queue=text_queue, send_event=send_event,
        )
        assert result["effective_seconds"] == 1
        await asyncio.sleep(1.5)

        from server.observability import get_artifact_buffer
        obs = get_artifact_buffer()
        prealert_events = [e for e in obs if e["event_type"] == "timer_prealert_fired"]
        expired_events = [e for e in obs if e["event_type"] == "timer_expired"]
        assert len(prealert_events) >= 1
        assert len(expired_events) >= 1

        assert text_queue.empty(), "Timer should not write directly to text_input_queue anymore"


class TestUpdateCookingStep:
    @pytest.mark.asyncio
    async def test_valid_transition(self, session, events):
        captured, send_event = events
        result = await update_cooking_step("prep", session=session, send_event=send_event)
        assert session.current_step == "prep"
        assert "Monitoring prep" in session.monitoring_status
        assert len(captured) == 1
        assert captured[0]["type"] == "state_update"

    @pytest.mark.asyncio
    async def test_heat_step_creates_milestone_candidate(self, session, events):
        captured, send_event = events
        session.recipe_name = "garlic butter chicken"
        await update_cooking_step("prep", session=session, send_event=send_event)
        result = await update_cooking_step("heat", session=session, send_event=send_event)
        assert session.current_step == "heat"

        from server.observability import get_artifact_buffer
        obs = get_artifact_buffer()
        created = [
            e for e in obs
            if e["event_type"] == "proactive_candidate_created"
            and e["details"]["reason_code"] == "step_entered_heat"
        ]
        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_invalid_backward(self, session, events):
        captured, send_event = events
        session.current_step = "sear_side_1"
        result = await update_cooking_step("prep", session=session, send_event=send_event)
        assert "error" in result
        assert session.current_step == "sear_side_1"

    @pytest.mark.asyncio
    async def test_invalid_step_name(self, session, events):
        captured, send_event = events
        result = await update_cooking_step("nonexistent", session=session, send_event=send_event)
        assert "error" in result


class TestUpdateRecipe:
    @pytest.mark.asyncio
    async def test_sets_recipe_name(self, session, events):
        captured, send_event = events
        result = await update_recipe(
            "garlic butter chicken", session=session, send_event=send_event,
        )
        assert session.recipe_name == "garlic butter chicken"
        assert result["recipe_name"] == "garlic butter chicken"
        assert len(captured) == 1
        assert captured[0]["type"] == "state_update"

    @pytest.mark.asyncio
    async def test_overwrites_recipe_name(self, session, events):
        captured, send_event = events
        session.recipe_name = "old recipe"
        result = await update_recipe(
            "new recipe", session=session, send_event=send_event,
        )
        assert session.recipe_name == "new recipe"


class TestGetCookingState:
    @pytest.mark.asyncio
    async def test_returns_snapshot(self, session):
        session.recipe_name = "chicken"
        session.current_step = "heat"
        result = await get_cooking_state(session=session)
        assert result["recipe_name"] == "chicken"
        assert result["current_step"] == "heat"
        assert isinstance(result["timers"], list)
