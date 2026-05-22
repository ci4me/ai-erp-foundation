"""Tests for ``simulation/_live.py``.

Mocks the Anthropic SDK so we can exercise the live-mode logic without
network access, API keys, or money. Real live runs only happen in CI when
``ANTHROPIC_API_KEY`` is configured.

Closes issue #11 acceptance criterion: ``run_live()`` must have unit
coverage (Tessa REQUEST_CHANGES-equivalent on the follow-up).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from simulation import _live  # noqa: E402


def _mock_anthropic_response(text: str, tokens_in: int = 100, tokens_out: int = 200) -> MagicMock:
    """Build a fake anthropic Message response with the given text + token counts."""
    content = MagicMock()
    content.text = text
    response = MagicMock()
    response.content = [content]
    response.usage.input_tokens = tokens_in
    response.usage.output_tokens = tokens_out
    return response


# ---------- extract_verdict ----------------------------------------------------

def test_extract_verdict_finds_bold_markdown() -> None:
    assert _live.extract_verdict("\n**Verdict:** REQUEST_CHANGES\n") == "REQUEST_CHANGES"


def test_extract_verdict_finds_plain_form() -> None:
    assert _live.extract_verdict("Verdict: BLOCKED") == "BLOCKED"


def test_extract_verdict_normalizes_dashes_to_underscores() -> None:
    assert _live.extract_verdict("**Verdict:** APPROVE-WITH-CONDITIONS") == "APPROVE_WITH_CONDITIONS"


def test_extract_verdict_returns_none_when_missing() -> None:
    assert _live.extract_verdict("looks good to me") is None


# ---------- flaw_mentioned -----------------------------------------------------

def test_flaw_mentioned_by_id() -> None:
    flaw = {"id": "F1", "name": "missing actor parameter"}
    assert _live.flaw_mentioned(flaw, "I see F1 referenced in the diff") is True


def test_flaw_mentioned_by_keyword_majority() -> None:
    flaw = {"id": "F2", "name": "missing domain event on state transition"}
    text = "The aggregate state transition does not emit a domain event"
    assert _live.flaw_mentioned(flaw, text) is True


def test_flaw_not_mentioned_when_keywords_absent() -> None:
    flaw = {"id": "F3", "name": "error_log used as audit mechanism"}
    assert _live.flaw_mentioned(flaw, "the code looks fine") is False


def test_flaw_mentioned_threshold_is_majority_for_short_names() -> None:
    flaw = {"id": "F4", "name": "method too long"}
    # Two keywords ("method", "long"); both present → caught
    assert _live.flaw_mentioned(flaw, "this method is too long") is True


# ---------- count_hallucinations ----------------------------------------------

def test_count_hallucinations_finds_invented_symbols() -> None:
    diff = "+ public function suspend(string $reason): void"
    text = "I noticed `suspend` and also `frobnicate()` and `bogusMethod`"
    halls = _live.count_hallucinations(text, diff)
    assert any("frobnicate" in h for h in halls)
    assert any("bogusMethod" in h for h in halls)


def test_count_hallucinations_ignores_diff_symbols() -> None:
    diff = "+ public function suspend(string $reason): void"
    text = "Looks at `suspend` and `reason`"
    assert _live.count_hallucinations(text, diff) == []


def test_count_hallucinations_allow_lists_common_terms() -> None:
    diff = "x"
    text = "I ran `pytest` and saw `PASS` and `NotImplementedError`"
    assert _live.count_hallucinations(text, diff) == []


# ---------- compute_cost ------------------------------------------------------

def test_compute_cost_matches_opus_pricing() -> None:
    # 1M input + 1M output @ Opus = 15 + 75 = 90 USD
    assert _live.compute_cost(1_000_000, 1_000_000, "claude-opus-4-7") == 90.0


def test_compute_cost_matches_haiku_pricing() -> None:
    # 1M input + 1M output @ Haiku 4.5 = 1 + 5 = 6 USD
    assert _live.compute_cost(1_000_000, 1_000_000, "claude-haiku-4-5") == 6.0


def test_compute_cost_falls_back_to_opus_for_unknown_model() -> None:
    known = _live.compute_cost(1_000_000, 1_000_000, "claude-opus-4-7")
    unknown = _live.compute_cost(1_000_000, 1_000_000, "model-from-the-future")
    assert unknown == known


# ---------- create_client -----------------------------------------------------

def test_create_client_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _live.create_client()


# ---------- dispatch_persona (integration with mocks) -------------------------

@patch("simulation._live.anthropic.Anthropic")
def test_dispatch_persona_assembles_response_into_persona_result(
    mock_anthropic: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts_dir = tmp_path / ".github" / "agent-prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "_preamble.md").write_text("Universal preamble text.")
    (prompts_dir / "test-persona.md").write_text(
        "---\n"
        "model_default: claude-haiku-4-5\n"
        "inherits_preamble: true\n"
        "---\n"
        "You are Test Persona."
    )
    monkeypatch.setattr(_live, "_PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(_live, "_PREAMBLE_PATH", prompts_dir / "_preamble.md")

    client = mock_anthropic.return_value
    client.messages.create.return_value = _mock_anthropic_response(
        "**Verdict:** REQUEST_CHANGES\n\nFinding F1 — missing actor.",
        tokens_in=500,
        tokens_out=100,
    )

    scenario = {
        "id": "test-001",
        "mock_pr": {"title": "t", "body": "b", "diff": "d"},
        "planted_flaws": [{"id": "F1", "name": "missing actor", "severity": "high"}],
    }
    persona_spec = {
        "id": "test-persona",
        "expected_verdict": "REQUEST_CHANGES",
        "must_catch": ["F1"],
    }

    result = _live.dispatch_persona(client, "test-persona", persona_spec, scenario)
    assert result.verdict_actual == "REQUEST_CHANGES"
    assert result.verdict_match is True
    assert "F1" in result.flaws_caught
    assert result.flaws_missed == []
    assert result.hallucinations == []
    assert result.cost_usd > 0
    assert result.tokens_in == 500
    assert result.tokens_out == 100


# ---------- evaluate_scenario aggregation -------------------------------------

@patch("simulation._live.anthropic.Anthropic")
def test_evaluate_scenario_passes_when_all_personas_match(
    mock_anthropic: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts_dir = tmp_path / ".github" / "agent-prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "_preamble.md").write_text("")
    (prompts_dir / "p1.md").write_text(
        "---\nmodel_default: claude-haiku-4-5\ninherits_preamble: false\n---\nYou are P1."
    )
    monkeypatch.setattr(_live, "_PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(_live, "_PREAMBLE_PATH", prompts_dir / "_preamble.md")

    client = mock_anthropic.return_value
    client.messages.create.return_value = _mock_anthropic_response(
        "**Verdict:** REQUEST_CHANGES\n\nF1 caught.",
    )

    scenario = {
        "id": "test-002",
        "mock_pr": {"title": "t", "body": "b", "diff": "d"},
        "planted_flaws": [{"id": "F1", "name": "thing", "severity": "high"}],
        "personas": [{"id": "p1", "expected_verdict": "REQUEST_CHANGES", "must_catch": ["F1"]}],
        "pass_threshold": {
            "flaws_caught_pct": 70,
            "hallucinations_allowed": 0,
            "per_persona_verdict_match": True,
        },
    }
    result = _live.evaluate_scenario(client, scenario, max_cost_per_scenario_usd=1.0)
    assert result.passed is True
    assert len(result.personas) == 1
    assert result.failure_reasons == []


@patch("simulation._live.anthropic.Anthropic")
def test_evaluate_scenario_fails_on_verdict_mismatch(
    mock_anthropic: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts_dir = tmp_path / ".github" / "agent-prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "_preamble.md").write_text("")
    (prompts_dir / "p1.md").write_text(
        "---\nmodel_default: claude-haiku-4-5\ninherits_preamble: false\n---\nYou are P1."
    )
    monkeypatch.setattr(_live, "_PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(_live, "_PREAMBLE_PATH", prompts_dir / "_preamble.md")

    client = mock_anthropic.return_value
    client.messages.create.return_value = _mock_anthropic_response(
        "**Verdict:** APPROVE\n\nLooks great to me.",
    )

    scenario = {
        "id": "test-003",
        "mock_pr": {"title": "t", "body": "b", "diff": "d"},
        "planted_flaws": [{"id": "F1", "name": "thing", "severity": "high"}],
        "personas": [{"id": "p1", "expected_verdict": "REQUEST_CHANGES", "must_catch": ["F1"]}],
        "pass_threshold": {
            "flaws_caught_pct": 70,
            "hallucinations_allowed": 0,
            "per_persona_verdict_match": True,
        },
    }
    result = _live.evaluate_scenario(client, scenario, max_cost_per_scenario_usd=1.0)
    assert result.passed is False
    assert any("verdict mismatch" in r for r in result.failure_reasons)


# ---------- scorecard emission ------------------------------------------------

def test_write_scorecard_creates_json_with_expected_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_live, "_SCORECARDS_DIR", tmp_path)
    result = _live.PersonaResult(
        persona_id="p1",
        model="claude-haiku-4-5",
        verdict_expected="REQUEST_CHANGES",
        verdict_actual="REQUEST_CHANGES",
        verdict_match=True,
        must_catch=["F1"],
        flaws_caught=["F1", "F2"],
        flaws_missed=[],
        hallucinations=[],
        tokens_in=500,
        tokens_out=100,
        cost_usd=0.0006,
        raw_response="ignored",
    )
    _live.write_scorecard(result, "test-001")
    path = tmp_path / "p1.json"
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["persona_id"] == "p1"
    assert "test-001" in data["scenarios"]
    entry = data["scenarios"]["test-001"]
    assert entry["verdict_matched"] is True
    assert entry["flaws_caught"] == ["F1", "F2"]
    assert entry["cost_usd"] == 0.0006


def test_write_scorecard_appends_to_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_live, "_SCORECARDS_DIR", tmp_path)
    existing = tmp_path / "p1.json"
    existing.write_text(json.dumps({
        "persona_id": "p1",
        "scenarios": {"prior-run": {"verdict_matched": False}},
    }))

    result = _live.PersonaResult(
        persona_id="p1",
        model="claude-haiku-4-5",
        verdict_expected="APPROVE",
        verdict_actual="APPROVE",
        verdict_match=True,
        must_catch=[],
        flaws_caught=[],
        flaws_missed=[],
        hallucinations=[],
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.0001,
        raw_response="ignored",
    )
    _live.write_scorecard(result, "new-run")

    data = json.loads(existing.read_text())
    assert "prior-run" in data["scenarios"]
    assert "new-run" in data["scenarios"]
