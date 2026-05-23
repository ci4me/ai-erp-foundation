"""Planning-first workflow end-to-end and unit tests.

Covers the lifecycle from ``PLAN-REQUEST`` discussion to ``RELEASE-NOTES``
close, including:

- orchestrator state machine transitions (`_planning_state`),
- AC enforcement in `validator.validate_acceptance_criteria`,
- per-action schema validation for the 6 new actions,
- the safety rule that implementation cannot precede an approved plan.
"""

from __future__ import annotations

from simulation.tools import lock as lock_mod
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import validator


REPO = "test-org/test-repo"


def _issue(number, *, body="", comments=None, labels=None, updated=None):
    return {
        "number": number,
        "body": body,
        "comments": [{"body": c} for c in (comments or [])],
        "labels": [{"name": name} for name in (labels or [])],
        "updatedAt": updated,
    }


# --------------------------------------------------------------------------
# State machine.
# --------------------------------------------------------------------------


def test_plan_request_triggers_facilitate_planning():
    issue = _issue(100, body="PLAN-REQUEST: Add notifications.\n")
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "facilitate_planning"


def test_plan_ready_triggers_promote_to_issues():
    body = (
        "PLAN-REQUEST: ...\n"
        "PLAN-SUMMARY: build notification module.\n"
        "PLAN-READY: POSTED\n"
    )
    issue = _issue(101, body=body)
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "promote_to_issues"


def test_plan_approve_comment_triggers_validate_plan():
    issue = _issue(
        102,
        body="PLAN-STATUS: DRAFT\n- [ ] AC1: do thing",
        comments=["PLAN-APPROVE looks good"],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "validate_plan"


def test_plan_approved_triggers_implement_with_ac():
    issue = _issue(103, body="PLAN-STATUS: APPROVED\n- [ ] AC1: do x")
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "implement_with_ac"


def test_plan_status_draft_without_approve_falls_through():
    """Without a PLAN-APPROVE the loop should not over-ride to validate_plan."""
    issue = _issue(104, body="PLAN-STATUS: DRAFT\n- [ ] AC1: x")
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="implement_issue",
        runner=lock_mod.InMemoryGh(),
    )
    # No planning override; orchestrator may still apply other guards but
    # not the validate_plan one.
    assert decision.action_override != "validate_plan"


# --------------------------------------------------------------------------
# AC enforcement.
# --------------------------------------------------------------------------


def test_acceptance_criteria_must_be_referenced():
    body = "- [ ] AC1: endpoint returns 200\n- [ ] AC2: response time < 100ms"
    impl = "AC1 is satisfied by the new endpoint. The other criterion was skipped."
    ok, missing = validator.validate_acceptance_criteria(body, impl)
    assert ok is False
    assert missing == ["AC2"]


def test_acceptance_criteria_all_present_passes():
    body = "- [ ] AC1: x\n- [ ] AC2: y"
    impl = "AC1 satisfied by endpoint test; AC2 satisfied by perf test."
    ok, missing = validator.validate_acceptance_criteria(body, impl)
    assert ok is True
    assert missing == []


# --------------------------------------------------------------------------
# Schema validation for the 6 new actions.
# --------------------------------------------------------------------------


def test_facilitate_planning_schema_minimal_pass():
    validator.reset_schema_cache()
    body = (
        "## Steps\n\nWe asked three clarifying questions and produced the summary.\n\n"
        "PLAN-READY: POSTED\n"
    )
    result = validator.validate_action_output("facilitate_planning", body)
    assert result.valid is True, result.missing_items


def test_validate_plan_schema_rejects_unknown_status():
    validator.reset_schema_cache()
    body = (
        "## Validation rules\n\nWe checked the AC count and testability.\n\n"
        "PLAN-STATUS: MAYBE\n"
    )
    result = validator.validate_action_output("validate_plan", body)
    assert result.valid is False
    assert any("PLAN-STATUS" in item for item in result.missing_items)


def test_implement_with_ac_demands_each_ac():
    validator.reset_schema_cache()
    body = (
        "## Acceptance criteria coverage\n\nAC1 done. AC2 done.\n\n"
        "## Testing performed\n\nAll tests pass.\n\nAC-COVERAGE: POSTED\n"
    )
    result = validator.validate_action_output(
        "implement_with_ac",
        body,
        issue_context={
            "body": "- [ ] AC1: do x\n- [ ] AC2: do y\n- [ ] AC3: do z",
            "labels": [],
        },
    )
    assert result.valid is False
    assert any("AC3" in item for item in result.missing_items)


def test_close_plan_schema_validates_when_marker_present():
    validator.reset_schema_cache()
    body = (
        "## Steps\n\nClosed milestone and stored retrospective lesson.\n\n"
        "RELEASE-NOTES: POSTED\n"
    )
    result = validator.validate_action_output("close_plan", body)
    assert result.valid is True, result.missing_items
