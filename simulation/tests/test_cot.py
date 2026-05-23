"""Chain-of-Thought scenarios.

Covers, per the system-improvement spec:

- trivial: 2 steps × 5 words passes;
- medium: 3 steps × 8 words passes;
- complex: 5 steps × 12 words passes (and 4 steps fails);
- missing reasoning section fails with a helpful message;
- identical CoT twice in the same issue triggers the loop-breaker.
"""

from __future__ import annotations

from simulation.tools import complexity, decision_log
from simulation.tools import lock as lock_mod
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import validator


# --------------------------------------------------------------------------
# Complexity detector.
# --------------------------------------------------------------------------


def test_complexity_trivial_via_label():
    spec = complexity.detect_complexity("fix wording", ["trivial"])
    assert spec["level"] == "trivial"
    assert spec["min_steps"] == 2
    assert spec["min_words_per_step"] == 5


def test_complexity_complex_via_keyword():
    spec = complexity.detect_complexity("redesign the auth API for tenants", [])
    assert spec["level"] == "complex"
    assert spec["min_steps"] == 5
    assert spec["min_words_per_step"] == 12


def test_complexity_medium_default():
    spec = complexity.detect_complexity("add a banner to the dashboard", [])
    assert spec["level"] == "medium"


def test_complexity_short_override_label():
    spec = complexity.detect_complexity(
        "redesign the auth API",
        ["cot-short", "complex"],
    )
    assert spec["level"] == "trivial"


# --------------------------------------------------------------------------
# CoT extraction and length validation.
# --------------------------------------------------------------------------


TRIVIAL_OUTPUT = """
**Reasoning:**
1. Read the typo in README opening paragraph.
2. Apply the spelling fix to README intro.

IMPLEMENTATION-COMPLETE: TRUE
"""


def test_cot_trivial_passes():
    ok, msg = validator.validate_cot(TRIVIAL_OUTPUT, "fix typo", ["trivial"])
    assert ok, msg


MEDIUM_OUTPUT = """
**Reasoning:**
1. Identify which dashboard component owns the banner currently.
2. Decide where the new banner element should be rendered.
3. Plan the CSS change to honour responsive breakpoints.

IMPLEMENTATION-COMPLETE: TRUE
"""


def test_cot_medium_passes():
    ok, msg = validator.validate_cot(MEDIUM_OUTPUT, "add a banner to the dashboard", [])
    assert ok, msg


COMPLEX_OUTPUT = """
**Reasoning:**
1. Restate the goal: we will redesign the tenant API for backwards-compatible auth migration safely.
2. Review context: prior token decision recorded, two callers depend on the legacy endpoint.
3. List alternatives: gateway shim, parallel endpoint, full breakage with sunset window across services.
4. Plan the work: introduce gateway shim and migrate clients incrementally across two consecutive sprints.
5. Risks & mitigation: token replay attack, mitigated with short-lived signed JWT plus rotation policy.

IMPLEMENTATION-COMPLETE: TRUE
"""


def test_cot_complex_passes():
    ok, msg = validator.validate_cot(
        COMPLEX_OUTPUT,
        "redesign the auth API for multi-tenant security",
        [],
    )
    assert ok, msg


def test_cot_complex_fails_with_only_four_steps():
    truncated = "\n".join(COMPLEX_OUTPUT.splitlines()[:-3])  # drop step 5 + marker
    truncated += "\n\nIMPLEMENTATION-COMPLETE: TRUE\n"
    ok, msg = validator.validate_cot(
        truncated,
        "redesign the auth API for multi-tenant security",
        [],
    )
    assert ok is False
    assert "at least 5" in msg


def test_cot_missing_section_fails():
    body_without_cot = "Just shipping it.\n\nIMPLEMENTATION-COMPLETE: TRUE\n"
    ok, msg = validator.validate_cot(body_without_cot, "anything", [])
    assert ok is False
    assert "Missing" in msg and "Reasoning" in msg


def test_cot_short_steps_fail():
    bad_steps = "**Reasoning:**\n1. ok ok\n2. ok ok\n3. ok ok\n\nIMPLEMENTATION-COMPLETE: TRUE\n"
    ok, msg = validator.validate_cot(bad_steps, "add a banner to the dashboard", [])
    assert ok is False
    assert "words" in msg


# --------------------------------------------------------------------------
# Integration with validate_action_output.
# --------------------------------------------------------------------------


def test_validate_action_output_requires_cot():
    validator.reset_schema_cache()
    body_without_cot = """## Implementation

We added a new endpoint for cookie suspension. The handler is plumbed into the
existing router and we validated locally with the smoke suite.

## Changes made

- routes/cookie.py updated with the new handler
- tests/test_cookie.py covers the new path

IMPLEMENTATION-COMPLETE: TRUE
"""
    result = validator.validate_action_output(
        "implement_issue",
        body_without_cot,
        issue_context={"body": "add a banner", "labels": []},
    )
    assert result.valid is False
    assert any("Reasoning" in item for item in result.missing_items)


# --------------------------------------------------------------------------
# CoT storage in the decision log.
# --------------------------------------------------------------------------


def test_cot_storage_round_trip():
    body = "Issue title.\n\nDescription here.\n"
    entry = decision_log.CotEntry(
        timestamp="2026-05-23T10:30:00Z",
        agent="implementer",
        steps=5,
        content="restate; context; alternatives; plan; risks",
    )
    updated = decision_log.append_cot(body, entry)
    parsed = decision_log.parse_cot_entries(updated)
    assert len(parsed) == 1
    assert parsed[0].agent == "implementer"
    assert "restate" in parsed[0].content


def test_cot_storage_capped_at_max():
    body = ""
    for i in range(decision_log.MAX_STORED_COT_ENTRIES + 3):
        body = decision_log.append_cot(
            body,
            decision_log.CotEntry(
                timestamp=f"2026-05-{20+i:02d}T10:00:00Z",
                agent="implementer",
                steps=3,
                content=f"reasoning {i}",
            ),
        )
    parsed = decision_log.parse_cot_entries(body)
    assert len(parsed) == decision_log.MAX_STORED_COT_ENTRIES


# --------------------------------------------------------------------------
# Loop breaker: identical CoTs in a row escalates to UNRESOLVED.
# --------------------------------------------------------------------------


def test_identical_cot_twice_closes_as_unresolved():
    body = ""
    entry = decision_log.CotEntry(
        timestamp="2026-05-23T10:00:00Z",
        agent="implementer",
        steps=3,
        content="restate goal; review context; plan the work the same way again",
    )
    body = decision_log.append_cot(body, entry)
    body = decision_log.append_cot(
        body,
        decision_log.CotEntry(
            timestamp="2026-05-23T11:00:00Z",
            agent="implementer",
            steps=3,
            content="restate goal; review context; plan the work the same way again",
        ),
    )
    issue = {
        "number": 11,
        "body": body,
        "comments": [],
        "labels": [],
    }
    decision = orch.check_locks_and_cycles(
        repo="test/repo",
        issue=issue,
        proposed_action="design_solution",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert decision.context["issue_close_reason"] == "UNRESOLVED"
    assert "stuck-reasoning" in decision.context["add_labels"]
