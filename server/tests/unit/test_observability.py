"""Unit tests for observability module."""

from server.observability import (
    emit,
    get_run_id,
    reset_run_id,
    get_artifact_buffer,
    clear_artifact_buffer,
)


class TestEmit:
    def setup_method(self):
        clear_artifact_buffer()

    def test_returns_event(self):
        event = emit("test.component", "test_event")
        assert event["component"] == "test.component"
        assert event["event_type"] == "test_event"
        assert "timestamp" in event
        assert "run_id" in event

    def test_buffers_events(self):
        emit("a", "evt1")
        emit("b", "evt2")
        buf = get_artifact_buffer()
        assert len(buf) == 2

    def test_session_id(self):
        event = emit("c", "evt", session_id="s123")
        assert event["session_id"] == "s123"

    def test_details(self):
        event = emit("c", "evt", details={"key": "val"})
        assert event["details"]["key"] == "val"

    def test_severity(self):
        event = emit("c", "evt", severity="ERROR")
        assert event["severity"] == "ERROR"


class TestRunId:
    def test_get_run_id(self):
        rid = get_run_id()
        assert rid.startswith("run_")

    def test_reset_run_id(self):
        old = get_run_id()
        new = reset_run_id("custom_123")
        assert new == "custom_123"
        assert get_run_id() == "custom_123"
        reset_run_id()  # restore
