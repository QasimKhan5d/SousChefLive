"""Scenario loader for SousChef Live harness.

Loads YAML scenario files and converts them into fake scripts
compatible with FakeGenaiClient.
"""

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def load_scenario(scenario_id: str) -> dict[str, Any]:
    """Load a scenario file by ID from the scenarios directory."""
    if yaml is None:
        raise RuntimeError("PyYAML is required: pip install pyyaml")

    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")

    with open(path) as f:
        return yaml.safe_load(f)


def scenario_to_fake_script(scenario: dict) -> list[dict]:
    """Extract the fake_script list from a loaded scenario."""
    return scenario.get("fake_script", [])


def list_scenarios() -> list[str]:
    """List all available scenario IDs."""
    if not SCENARIOS_DIR.exists():
        return []
    return sorted(
        p.stem for p in SCENARIOS_DIR.glob("*.yaml")
    )


def get_judge_critical_scenarios() -> list[str]:
    """Return IDs of scenarios marked as judge_critical."""
    critical = []
    for sid in list_scenarios():
        try:
            s = load_scenario(sid)
            if s.get("judge_critical"):
                critical.append(sid)
        except Exception:
            pass
    return critical
