"""App-owned conversation memory for SousChef Live.

Captures transcript turns, maintains a rolling summary of older dialogue,
and stores structured kitchen facts. Provides token estimation and
compaction decisions so the reconnect primer stays bounded.

Deterministic compaction can optionally use a cheap non-live Gemini model
to summarize older turns.
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)

COMPACTION_MODEL = os.getenv("COMPACTION_MODEL", "gemini-2.0-flash-lite")
COMPACTION_COOLDOWN_SECONDS = 120
_last_compaction_time: float = 0.0
_compaction_lock = asyncio.Lock()


@dataclass
class ConversationTurn:
    role: str
    text: str
    ts: float
    token_estimate: int = 0

    def __post_init__(self):
        if not self.token_estimate:
            self.token_estimate = max(1, len(self.text) // 4)


DEFAULT_FACT_CATEGORIES = {
    "preferences": [],
    "substitutions": [],
    "observations": [],
    "decisions": [],
}


@dataclass
class SessionMemory:
    recent_turns: deque = field(default_factory=lambda: deque(maxlen=100))
    rolling_summary: str = ""
    facts: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_FACT_CATEGORIES.items()}
    )
    compressed_through_ts: float = 0.0

    LOCAL_MEMORY_BUDGET_TOKENS: ClassVar[int] = 5000

    def estimated_tokens(self) -> int:
        turn_tokens = sum(t.token_estimate for t in self.recent_turns)
        summary_tokens = len(self.rolling_summary) // 4
        fact_tokens = sum(
            len(f) // 4 for fs in self.facts.values() for f in fs
        )
        return turn_tokens + summary_tokens + fact_tokens

    def needs_compaction(self) -> bool:
        return self.estimated_tokens() > int(self.LOCAL_MEMORY_BUDGET_TOKENS * 0.85)

    def add_turn(self, role: str, text: str, ts: float | None = None):
        if not text or not text.strip():
            return
        ts = ts or time.time()
        self.recent_turns.append(ConversationTurn(role=role, text=text, ts=ts))

    def compact(self, new_summary: str, new_facts: dict[str, list[str]] | None = None):
        """Replace old turns with a compacted summary and optional new facts."""
        if new_summary:
            if self.rolling_summary:
                self.rolling_summary = f"{self.rolling_summary}\n{new_summary}"
            else:
                self.rolling_summary = new_summary

        if new_facts:
            for category, items in new_facts.items():
                if category in self.facts:
                    for item in items:
                        if item not in self.facts[category]:
                            self.facts[category].append(item)

        now = time.time()
        keep_count = min(20, len(self.recent_turns))
        while len(self.recent_turns) > keep_count:
            self.recent_turns.popleft()
        self.compressed_through_ts = now

    def simple_truncate(self):
        """Fallback compaction: just drop oldest turns without summarization."""
        keep_count = min(20, len(self.recent_turns))
        while len(self.recent_turns) > keep_count:
            self.recent_turns.popleft()
        self.compressed_through_ts = time.time()

    def format_for_primer(self, max_recent: int = 10, max_facts_per_category: int = 5) -> str:
        """Build the memory portion of a reconnect primer."""
        parts = []

        if self.rolling_summary:
            parts.append(f"Conversation summary:\n{self.rolling_summary}")

        for category, items in self.facts.items():
            if items:
                parts.append(f"\n{category.replace('_', ' ').title()}:")
                for item in items[-max_facts_per_category:]:
                    parts.append(f"- {item}")

        if self.recent_turns:
            parts.append("\nRecent dialogue:")
            for turn in list(self.recent_turns)[-max_recent:]:
                label = "Cook" if turn.role == "cook" else "Chef"
                parts.append(f"{label}: {turn.text}")

        return "\n".join(parts)


COMPACTION_PROMPT = """You are a kitchen conversation summarizer. Given a cooking session dialogue excerpt, produce a JSON object with exactly two keys:
- "summary": a 2-3 sentence summary of what happened in this excerpt
- "facts": an object with keys "preferences", "substitutions", "observations", "decisions", each containing a list of short strings

Only include facts that are clearly stated. Be concise.

Dialogue:
{dialogue}

Respond with ONLY valid JSON, no markdown fences."""


async def run_compaction(memory: SessionMemory, api_key: str) -> bool:
    """Attempt to compact older turns using a cheap model.

    Returns True if compaction succeeded, False otherwise.
    Rate-limited to one call per COMPACTION_COOLDOWN_SECONDS.
    Non-blocking: should be called via asyncio.create_task().
    """
    global _last_compaction_time

    if not memory.needs_compaction():
        return False

    now = time.time()
    if now - _last_compaction_time < COMPACTION_COOLDOWN_SECONDS:
        memory.simple_truncate()
        return False

    async with _compaction_lock:
        if not memory.needs_compaction():
            return False

        turns_to_compact = []
        keep_count = min(20, len(memory.recent_turns))
        total = len(memory.recent_turns)
        compact_count = total - keep_count

        if compact_count <= 0:
            memory.simple_truncate()
            return False

        turns_list = list(memory.recent_turns)
        turns_to_compact = turns_list[:compact_count]

        dialogue_lines = []
        for t in turns_to_compact:
            label = "Cook" if t.role == "cook" else "Chef"
            dialogue_lines.append(f"{label}: {t.text}")
        dialogue_text = "\n".join(dialogue_lines)

        if len(dialogue_text) < 50:
            memory.simple_truncate()
            return False

        try:
            import google.genai as genai
            client = genai.Client(api_key=api_key)
            prompt = COMPACTION_PROMPT.format(dialogue=dialogue_text)

            response = await client.aio.models.generate_content(
                model=COMPACTION_MODEL,
                contents=prompt,
            )

            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                if text.endswith("```"):
                    text = text[:-3].strip()

            result = json.loads(text)
            new_summary = result.get("summary", "")
            new_facts = result.get("facts", {})

            memory.compact(new_summary, new_facts)
            _last_compaction_time = time.time()
            logger.info("Compaction succeeded: %d turns compacted", compact_count)
            return True

        except Exception as e:
            logger.warning("Compaction LLM call failed, falling back to truncation: %s", e)
            memory.simple_truncate()
            _last_compaction_time = time.time()
            return False
