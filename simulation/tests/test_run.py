"""Unit tests for ``simulation/run.py``.

These tests exist because Tessa (Test Lead) REQUEST_CHANGES'd PR #10
specifically because the regression gate had zero coverage — meaning the
gate itself could degrade silently. Each test below corresponds to a
named failure mode Tessa called out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Allow running from the repo root (CI) or from simulation/ directly.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from simulation import run as r  # noqa: E402  (path fixup above)


@pytest.fixture
def valid_scenario() -> dict:
    """A minimal scenario that should validate cleanly against the schema."""
    return {
        "id": "999-fixture-valid",
        "title": "Minimal valid scenario fixture",
        "status": "active",
        "mock_pr": {"title": "t", "body": "b", "diff": "d"},
        "planted_flaws": [{"id": "F1", "name": "test flaw", "severity": "high"}],
        "personas": [
            {"id": "theo-architect", "expected_verdict": "REQUEST_CHANGES", "must_catch": ["F1"]}
        ],
        "expected_overall_verdict": "BLOCKED",
        "pass_threshold": {
            "flaws_caught_pct": 70,
            "hallucinations_allowed": 0,
            "per_persona_verdict_match": True,
        },
    }


def test_validate_scenario_passes_on_valid(valid_scenario: dict) -> None:
    schema = r.load_schema()
    assert r.validate_scenario(valid_scenario, schema) == []


def test_validate_scenario_rejects_missing_required_field(valid_scenario: dict) -> None:
    del valid_scenario["id"]
    schema = r.load_schema()
    errors = r.validate_scenario(valid_scenario, schema)
    assert errors, "deleting required 'id' must produce a schema error"


def test_validate_scenario_rejects_unknown_top_level_field(valid_scenario: dict) -> None:
    """`additionalProperties: false` must reject unknown keys (Theo's closed-world rule)."""
    valid_scenario["extra_unknown_field"] = "value"
    schema = r.load_schema()
    errors = r.validate_scenario(valid_scenario, schema)
    assert errors, "unknown top-level field must be rejected by additionalProperties: false"


def test_check_persona_references_flags_missing(valid_scenario: dict) -> None:
    missing = r.check_persona_references(valid_scenario, available_personas={"ari-orchestrator"})
    assert missing == ["theo-architect"]


def test_check_persona_references_passes_when_all_present(valid_scenario: dict) -> None:
    missing = r.check_persona_references(
        valid_scenario, available_personas={"theo-architect", "ari-orchestrator"}
    )
    assert missing == []


def test_scenario_001_validates_against_schema() -> None:
    """The shipped scenario MUST round-trip through the schema."""
    schema = r.load_schema()
    scenarios = r.discover_scenarios()
    suspend_cookie = next((p for p in scenarios if "001-suspend-cookie" in p.name), None)
    assert suspend_cookie is not None, "scenario 001-suspend-cookie.yml must exist"
    with suspend_cookie.open() as fh:
        scenario = yaml.safe_load(fh)
    errors = r.validate_scenario(scenario, schema)
    assert errors == [], f"scenario 001 failed schema validation: {errors}"


def test_pass_threshold_not_silently_lowered() -> None:
    """Tessa's mutation guard: if anyone weakens the threshold, fail loudly."""
    for path in r.discover_scenarios():
        with path.open() as fh:
            scenario = yaml.safe_load(fh)
        threshold = scenario["pass_threshold"]
        assert threshold["flaws_caught_pct"] >= 70, (
            f"{path.name}: flaws_caught_pct={threshold['flaws_caught_pct']} below 70 "
            "— this is silent regression weakening"
        )
        assert threshold["hallucinations_allowed"] == 0, (
            f"{path.name}: hallucinations_allowed must be 0"
        )
        assert threshold["per_persona_verdict_match"] is True, (
            f"{path.name}: per_persona_verdict_match must be True"
        )


def test_live_mode_raises_not_implemented_with_documented_message() -> None:
    """Prism's contract test: live-mode shim must STAY a shim until follow-up PR."""
    schema = r.load_schema()
    scenarios = r.discover_scenarios()
    personas = r.discover_personas()
    with pytest.raises(NotImplementedError, match="Live mode is not yet wired"):
        r.run_live(scenarios, schema, personas)


def test_status_field_warns_on_non_active(valid_scenario: dict, capsys) -> None:
    """Theo's retirement-policy hook: non-active scenarios must emit a warning."""
    schema = r.load_schema()
    # Force a non-active status — should validate against schema but warn at runtime.
    valid_scenario["status"] = "deprecated"
    errors = r.validate_scenario(valid_scenario, schema)
    assert errors == [], "deprecated status should still validate against schema"
    # Runtime check via run_dry path requires the file system; tested via _check_status helper:
    warned = r._scenario_warning(valid_scenario)
    assert warned is not None
    assert "deprecated" in warned
