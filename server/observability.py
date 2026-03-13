"""Structured instrumentation for SousChef Live.

Provides JSON logging and event emission for both harness validation
and Cloud Run log ingestion. Every backend lifecycle event flows
through emit() so harness tiers can assert on structured artifacts.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

LOG_FORMAT = os.getenv("LOG_FORMAT", "json")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
HARNESS_ARTIFACT_DIR = os.getenv("HARNESS_ARTIFACT_DIR", "")
HARNESS_SCENARIO = os.getenv("HARNESS_SCENARIO", "")

_run_id: str = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
_artifact_buffer: list[dict] = []


def get_run_id() -> str:
    return _run_id


def reset_run_id(new_id: str | None = None) -> str:
    global _run_id
    _run_id = new_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return _run_id


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "severity": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event_data"):
            payload.update(record.event_data)
        return json.dumps(payload, default=str)


class _PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        if hasattr(record, "event_data"):
            return f"{base} | {json.dumps(record.event_data, default=str)}"
        return base


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler()
    if LOG_FORMAT == "json":
        handler.setFormatter(_JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    else:
        handler.setFormatter(
            _PlainFormatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
    root.addHandler(handler)


def emit(
    component: str,
    event_type: str,
    *,
    session_id: str = "",
    severity: str = "INFO",
    latency_ms: float = 0,
    details: dict[str, Any] | None = None,
) -> dict:
    """Emit a structured observability event.

    Logs it and optionally buffers it for artifact output.
    Returns the event dict for inline assertions in tests.
    """
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}Z",
        "run_id": _run_id,
        "session_id": session_id,
        "component": component,
        "event_type": event_type,
        "severity": severity,
        "latency_ms": latency_ms,
        "details": details or {},
    }
    if HARNESS_SCENARIO:
        event["scenario_id"] = HARNESS_SCENARIO

    _artifact_buffer.append(event)

    logger = logging.getLogger(component)
    level = getattr(logging, severity.upper(), logging.INFO)
    record = logger.makeRecord(
        component, level, "", 0, event_type, (), None
    )
    record.event_data = event  # type: ignore[attr-defined]
    logger.handle(record)

    return event


def flush_artifacts(run_dir: str | None = None) -> Path | None:
    """Write buffered events to report.json inside the run directory."""
    target = run_dir or HARNESS_ARTIFACT_DIR
    if not target:
        return None

    out = Path(target) / _run_id
    out.mkdir(parents=True, exist_ok=True)
    report = out / "report.json"
    report.write_text(json.dumps(_artifact_buffer, indent=2, default=str))
    return report


def get_artifact_buffer() -> list[dict]:
    """Return the in-memory event buffer (useful for test assertions)."""
    return _artifact_buffer


def clear_artifact_buffer() -> None:
    _artifact_buffer.clear()


setup_logging()
