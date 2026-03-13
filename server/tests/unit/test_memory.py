"""Unit tests for SessionMemory and conversation memory."""

import time
import pytest

from server.memory import ConversationTurn, SessionMemory


class TestConversationTurn:
    def test_auto_token_estimate(self):
        t = ConversationTurn(role="cook", text="Hello there chef", ts=time.time())
        assert t.token_estimate == max(1, len("Hello there chef") // 4)

    def test_explicit_token_estimate(self):
        t = ConversationTurn(role="cook", text="Hi", ts=time.time(), token_estimate=50)
        assert t.token_estimate == 50

    def test_empty_text_minimum(self):
        t = ConversationTurn(role="cook", text="ab", ts=time.time())
        assert t.token_estimate >= 1


class TestSessionMemory:
    def test_add_turn(self):
        mem = SessionMemory()
        mem.add_turn("cook", "I'm going to sear the chicken now")
        assert len(mem.recent_turns) == 1
        assert mem.recent_turns[0].role == "cook"

    def test_add_turn_ignores_empty(self):
        mem = SessionMemory()
        mem.add_turn("cook", "")
        mem.add_turn("cook", "   ")
        assert len(mem.recent_turns) == 0

    def test_estimated_tokens(self):
        mem = SessionMemory()
        mem.add_turn("cook", "Hello" * 100)
        tokens = mem.estimated_tokens()
        assert tokens > 0

    def test_estimated_tokens_includes_summary(self):
        mem = SessionMemory()
        mem.rolling_summary = "A" * 400
        tokens = mem.estimated_tokens()
        assert tokens == 400 // 4

    def test_estimated_tokens_includes_facts(self):
        mem = SessionMemory()
        mem.facts["preferences"].append("prefers medium-rare")
        tokens = mem.estimated_tokens()
        assert tokens > 0

    def test_needs_compaction_false_when_small(self):
        mem = SessionMemory()
        mem.add_turn("cook", "Short message")
        assert mem.needs_compaction() is False

    def test_needs_compaction_true_when_large(self):
        mem = SessionMemory()
        for i in range(200):
            mem.add_turn("cook", f"This is a fairly long message number {i} " * 5)
        assert mem.needs_compaction() is True

    def test_compact(self):
        mem = SessionMemory()
        for i in range(50):
            mem.add_turn("cook", f"Message {i}")
        assert len(mem.recent_turns) == 50

        mem.compact("The cook prepared chicken.", {"preferences": ["likes garlic"]})
        assert len(mem.recent_turns) <= 20
        assert "prepared chicken" in mem.rolling_summary
        assert "likes garlic" in mem.facts["preferences"]

    def test_compact_appends_to_existing_summary(self):
        mem = SessionMemory()
        mem.rolling_summary = "Initial summary."
        for i in range(30):
            mem.add_turn("cook", f"Turn {i}")
        mem.compact("More happened.")
        assert "Initial summary." in mem.rolling_summary
        assert "More happened." in mem.rolling_summary

    def test_compact_deduplicates_facts(self):
        mem = SessionMemory()
        mem.facts["preferences"].append("likes garlic")
        for i in range(30):
            mem.add_turn("cook", f"Turn {i}")
        mem.compact("Summary", {"preferences": ["likes garlic", "dislikes cilantro"]})
        assert mem.facts["preferences"].count("likes garlic") == 1
        assert "dislikes cilantro" in mem.facts["preferences"]

    def test_simple_truncate(self):
        mem = SessionMemory()
        for i in range(60):
            mem.add_turn("cook", f"Message {i}")
        assert len(mem.recent_turns) == 60

        mem.simple_truncate()
        assert len(mem.recent_turns) <= 20
        assert mem.compressed_through_ts > 0

    def test_format_for_primer_empty(self):
        mem = SessionMemory()
        result = mem.format_for_primer()
        assert result == ""

    def test_format_for_primer_with_summary(self):
        mem = SessionMemory()
        mem.rolling_summary = "Cook is making garlic chicken."
        result = mem.format_for_primer()
        assert "Conversation summary:" in result
        assert "garlic chicken" in result

    def test_format_for_primer_with_facts(self):
        mem = SessionMemory()
        mem.facts["preferences"].append("medium-rare steak")
        result = mem.format_for_primer()
        assert "Preferences:" in result
        assert "medium-rare steak" in result

    def test_format_for_primer_with_recent_turns(self):
        mem = SessionMemory()
        mem.add_turn("cook", "How long should I sear?")
        mem.add_turn("chef", "About 4 minutes per side.")
        result = mem.format_for_primer()
        assert "Recent dialogue:" in result
        assert "Cook: How long should I sear?" in result
        assert "Chef: About 4 minutes per side." in result

    def test_format_for_primer_caps_recent(self):
        mem = SessionMemory()
        for i in range(30):
            mem.add_turn("cook", f"Message {i}")
        result = mem.format_for_primer(max_recent=5)
        lines = [l for l in result.split("\n") if l.startswith("Cook:")]
        assert len(lines) == 5

    def test_format_for_primer_caps_facts(self):
        mem = SessionMemory()
        for i in range(10):
            mem.facts["observations"].append(f"Observation {i}")
        result = mem.format_for_primer(max_facts_per_category=3)
        obs_lines = [l for l in result.split("\n") if l.startswith("- Observation")]
        assert len(obs_lines) == 3

    def test_deque_maxlen(self):
        mem = SessionMemory()
        for i in range(150):
            mem.add_turn("cook", f"Message {i}")
        assert len(mem.recent_turns) == 100


class TestEnhancedReconnectPrimer:
    """Test that build_reconnect_primer integrates memory."""

    def test_primer_includes_memory(self):
        from server.session_store import SessionContext, build_reconnect_primer
        ctx = SessionContext(session_id="s1", recipe_name="chicken", current_step="sear_side_1")
        ctx.memory.add_turn("cook", "Should I flip now?")
        ctx.memory.add_turn("chef", "Yes, flip it.")
        ctx.memory.rolling_summary = "Cook started searing chicken."

        primer = build_reconnect_primer(ctx)
        assert "chicken" in primer
        assert "sear_side_1" in primer
        assert "Conversation summary:" in primer
        assert "started searing" in primer
        assert "Recent dialogue:" in primer
        assert "Should I flip now?" in primer

    def test_primer_truncates_when_long(self):
        from server.session_store import SessionContext, build_reconnect_primer
        ctx = SessionContext(session_id="s1")
        ctx.memory.rolling_summary = "A" * 10000
        primer = build_reconnect_primer(ctx)
        assert len(primer) <= 8100
        assert "[...truncated]" in primer


class TestSessionContextMemoryIntegration:
    def test_session_has_memory(self):
        from server.session_store import SessionContext
        ctx = SessionContext(session_id="s1")
        assert hasattr(ctx, "memory")
        assert len(ctx.memory.recent_turns) == 0

    def test_session_has_resumption_handle(self):
        from server.session_store import SessionContext
        ctx = SessionContext(session_id="s1")
        assert ctx.resumption_handle is None

    def test_session_ended_field(self):
        from server.session_store import SessionContext
        ctx = SessionContext(session_id="s1")
        assert ctx.ended is False

    def test_is_expired_idle(self):
        from server.session_store import SessionContext, SESSION_IDLE_TTL
        ctx = SessionContext(session_id="s1")
        ctx.last_seen_at = time.time() - SESSION_IDLE_TTL - 1
        assert ctx.is_expired() is True

    def test_is_expired_max_age(self):
        from server.session_store import SessionContext, SESSION_MAX_AGE
        ctx = SessionContext(session_id="s1")
        ctx.started_at = time.time() - SESSION_MAX_AGE - 1
        assert ctx.is_expired() is True

    def test_not_expired_when_fresh(self):
        from server.session_store import SessionContext
        ctx = SessionContext(session_id="s1")
        assert ctx.is_expired() is False

    def test_state_snapshot_includes_transcript(self):
        from server.session_store import SessionContext
        ctx = SessionContext(session_id="s1")
        ctx.memory.add_turn("cook", "Hello chef")
        ctx.memory.add_turn("chef", "Hello cook")
        snap = ctx.to_state_snapshot()
        assert len(snap["transcript"]) == 2
        assert snap["transcript"][0]["role"] == "cook"
        assert snap["transcript"][0]["text"] == "Hello chef"
