"""Test simulation for the autonomous-loop audit fixes.

Covers, in this order:

1. Race condition with lock.
2. Unknown marker triggers clarification (and twice → close).
3. Cycle stops after 3 retries.
4. Issue with REVIEW-VERDICT: APPROVE but no PR -> closes.
5. Marker inside code block is ignored.
6. Timeout closes stale issue.
7. Missing PR on merge attempt -> close_issue.
8. Validation failures: missing section, missing marker, retry escalation.
9. Post-action verification: PR claimed but not created -> retry_implementation.
"""

from __future__ import annotations

import datetime as _dt

from simulation.tools import lock as lock_mod
from simulation.tools import loop_runner
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import post_action_verify
from simulation.tools import validator


REPO = "test-org/test-repo"


def _issue(
    number: int,
    *,
    body: str = "",
    comments: list[str] | None = None,
    labels: list[str] | None = None,
    updated: str | None = None,
) -> dict:
    return {
        "number": number,
        "body": body,
        "comments": [{"body": text} for text in (comments or [])],
        "labels": [{"name": name} for name in (labels or [])],
        "updatedAt": updated,
    }


# --------------------------------------------------------------------------
# 1. Race condition with lock.
# --------------------------------------------------------------------------


def test_lock_prevents_race_between_two_agents():
    fake = lock_mod.InMemoryGh()
    state_a = lock_mod.acquire(REPO, "issue:42", runner=fake)
    state_b = lock_mod.acquire(REPO, "issue:42", runner=fake)

    assert state_a.acquired is True
    assert state_b.acquired is False
    assert state_b.reason == "already-locked"

    lock_mod.release(REPO, "issue:42", runner=fake)
    state_c = lock_mod.acquire(REPO, "issue:42", runner=fake)
    assert state_c.acquired is True


def test_check_locks_and_cycles_aborts_when_locked():
    fake = lock_mod.InMemoryGh()
    lock_mod.acquire(REPO, "issue:7", runner=fake)
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=_issue(7),
        proposed_action="implement_issue",
        runner=fake,
    )
    assert decision.abort is True
    assert decision.reason == "locked"


# --------------------------------------------------------------------------
# 2. Unknown marker triggers clarification.
# --------------------------------------------------------------------------


def test_unknown_marker_routes_to_request_clarification():
    issue = _issue(
        9,
        body="Triaging this work.",
        comments=["MAGICAL-VERDICT: YES because reasons"],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "request_clarification"
    assert "MAGICAL-VERDICT" in decision.context["unknown_marker"]
    assert "REVIEW-VERDICT" in decision.context["valid_markers"]


# --------------------------------------------------------------------------
# 3. Cycle stops after 3 retries.
# --------------------------------------------------------------------------


def test_cycle_stops_after_three_design_retries():
    issue = _issue(
        11,
        body="Design pending.",
        comments=[
            "DESIGN-APPROVAL: REQUEST_CHANGES — pass 1",
            "DESIGN-APPROVAL: REQUEST_CHANGES — pass 2",
            "DESIGN-APPROVAL: REQUEST_CHANGES — pass 3",
            "DESIGN-APPROVAL: REQUEST_CHANGES — pass 4",  # exceeds 3
        ],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="design_solution",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert decision.context["issue_close_reason"] == "UNRESOLVED"
    assert "stuck" in decision.context["add_labels"]


def test_cycle_does_not_trip_when_progress_marker_present():
    issue = _issue(
        12,
        comments=[
            "DESIGN-APPROVAL: REQUEST_CHANGES",
            "DESIGN-APPROVAL: REQUEST_CHANGES",
            "DESIGN-APPROVAL: REQUEST_CHANGES",
            "DESIGN-APPROVAL: REQUEST_CHANGES",
            "REVIEW-VERDICT: APPROVE",
        ],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="design_solution",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override != "close_issue"


# --------------------------------------------------------------------------
# 4. APPROVE but no open PR -> consistency sweep closes the issue.
# --------------------------------------------------------------------------


def test_consistency_sweep_closes_approve_with_no_pr():
    open_issues = [_issue(20, comments=["REVIEW-VERDICT: APPROVE good to ship"])]
    findings = orch.consistency_sweep(
        open_issues=open_issues,
        open_prs=[],
        merged_prs=[],
    )
    assert len(findings) == 1
    assert findings[0].classification == "approve_no_pr"
    assert findings[0].issue_number == 20


def test_consistency_sweep_closes_merged_pr_with_open_issue():
    open_issues = [_issue(30)]
    merged_prs = [{"number": 99, "closingIssuesReferences": [{"number": 30}]}]
    findings = orch.consistency_sweep(
        open_issues=open_issues,
        open_prs=[],
        merged_prs=merged_prs,
    )
    assert any(f.classification == "merged_pr_open_issue" for f in findings)


def test_consistency_sweep_retries_close_when_done_marker_present():
    open_issues = [_issue(31, comments=["ISSUE-CLOSED: DONE — work complete"])]
    findings = orch.consistency_sweep(
        open_issues=open_issues,
        open_prs=[],
        merged_prs=[],
    )
    assert any(f.classification == "done_marker_still_open" for f in findings)


# --------------------------------------------------------------------------
# 5. Marker inside a code block is ignored.
# --------------------------------------------------------------------------


def test_marker_in_fenced_code_block_is_ignored():
    body = (
        "Example only:\n"
        "```\n"
        "REVIEW-VERDICT: APPROVE\n"
        "```\n"
        "Actual decision below.\n"
    )
    result = validator.parse_body(body)
    assert result.hits == []
    assert result.unknown == []


def test_marker_in_indented_code_block_is_ignored():
    body = "Real comment.\n\n    REVIEW-VERDICT: APPROVE\n"
    result = validator.parse_body(body)
    assert result.hits == []


def test_marker_outside_code_block_is_recognised():
    body = "Heads up team.\n\nREVIEW-VERDICT: APPROVE — looks fine."
    result = validator.parse_body(body)
    assert len(result.hits) == 1
    assert result.hits[0].value == "APPROVE"
    assert result.hits[0].extra_text.startswith("—") or result.hits[0].extra_text.startswith("- ")


def test_invalid_value_is_rejected():
    body = "REVIEW-VERDICT: MAYBE"
    result = validator.parse_body(body)
    assert result.hits == []
    assert len(result.invalid) == 1
    assert result.invalid[0].value == "MAYBE"


def test_case_insensitive_marker_parsing():
    body = "review-verdict:    approve  because CI green"
    result = validator.parse_body(body)
    assert len(result.hits) == 1
    assert result.hits[0].marker == "REVIEW-VERDICT"
    assert result.hits[0].value == "APPROVE"


def test_short_approval_is_flagged_suspicious():
    body = "REVIEW-VERDICT: APPROVE"
    result = validator.parse_body(body, comment_length=len(body))
    assert result.hits[0].suspicious is True


# --------------------------------------------------------------------------
# 6. Timeout closes stale issue.
# --------------------------------------------------------------------------


def test_timeout_closes_stale_defer_issue():
    nine_days_ago = (
        _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(days=9)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = _issue(
        77,
        comments=["TRIAGE-DECISION: DEFER — waiting on partner"],
        updated=nine_days_ago,
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert decision.context["issue_close_reason"] == "TIMEOUT"


def test_timeout_does_not_fire_within_budget():
    fresh = (
        _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(days=2)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = _issue(
        78,
        comments=["TRIAGE-DECISION: DEFER"],
        updated=fresh,
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override is None


# --------------------------------------------------------------------------
# 7. Missing PR on merge -> close_issue with REJECTED.
# --------------------------------------------------------------------------


def test_merge_pr_with_missing_pr_routes_to_close_issue():
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=_issue(50),
        proposed_action="merge_pr",
        proposed_pr_number=123,
        open_prs=[],
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert "PR not found" in decision.context["close_comment"]


# --------------------------------------------------------------------------
# 8. Validation against per-action schemas.
# --------------------------------------------------------------------------


VALID_IMPLEMENT_OUTPUT = """
## Implementation

We added a new endpoint for cookie suspension. The handler is plumbed into the
existing router and we validated locally with the smoke suite.

## Changes made

- routes/cookie.py updated with the new handler
- tests/test_cookie.py covers the new path

IMPLEMENTATION-COMPLETE: TRUE
"""


def test_validate_action_output_accepts_well_formed_output():
    validator.reset_schema_cache()
    result = validator.validate_action_output("implement_issue", VALID_IMPLEMENT_OUTPUT)
    assert result.valid is True
    assert result.missing_items == []


def test_validate_action_output_rejects_missing_section():
    validator.reset_schema_cache()
    missing_changes = VALID_IMPLEMENT_OUTPUT.replace(
        "## Changes made\n\n- routes/cookie.py updated with the new handler\n- tests/test_cookie.py covers the new path\n\n",
        "",
    )
    result = validator.validate_action_output("implement_issue", missing_changes)
    assert result.valid is False
    assert any("Changes made" in item for item in result.missing_items)


def test_validate_action_output_rejects_missing_marker():
    validator.reset_schema_cache()
    no_marker = VALID_IMPLEMENT_OUTPUT.replace("IMPLEMENTATION-COMPLETE: TRUE", "")
    result = validator.validate_action_output("implement_issue", no_marker)
    assert result.valid is False
    assert any("IMPLEMENTATION-COMPLETE" in item for item in result.missing_items)


def test_validate_action_output_rejects_invalid_marker_value():
    validator.reset_schema_cache()
    bad = VALID_IMPLEMENT_OUTPUT.replace(
        "IMPLEMENTATION-COMPLETE: TRUE", "IMPLEMENTATION-COMPLETE: MAYBE"
    )
    result = validator.validate_action_output("implement_issue", bad)
    assert result.valid is False


def test_retry_counter_escalates_after_max_retries():
    fake = lock_mod.InMemoryGh()
    target = "issue:99"
    for expected in (1, 2, 3):
        count = loop_runner.bump_retry_label(REPO, target, "implement_issue", runner=fake)
        assert count == expected
    # After 3 bumps the loop_runner would escalate (> MAX_VALIDATION_RETRIES=2).
    assert loop_runner.retry_count_from_labels(
        fake.labels[target], "implement_issue"
    ) == 3


# --------------------------------------------------------------------------
# 9. Post-action verification.
# --------------------------------------------------------------------------


def test_verify_pr_created_passes_when_branch_matches():
    now = _dt.datetime.now(tz=_dt.UTC)
    created = (now - _dt.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = post_action_verify.verify_pr_created(
        42,
        {"head_branch_pattern": "feature/issue-{{issue.number}}", "max_age_minutes": 30},
        open_prs=[{"number": 7, "headRefName": "feature/issue-42", "createdAt": created}],
        now=now,
    )
    assert result.ok is True


def test_verify_pr_created_fails_when_no_pr_exists():
    result = post_action_verify.verify_pr_created(
        42,
        {"head_branch_pattern": "feature/issue-{{issue.number}}"},
        open_prs=[],
    )
    assert result.ok is False
    assert result.failure_marker == "IMPLEMENTATION-COMPLETE: FAILED"
    assert result.next_action == "retry_implementation"


def test_verify_pr_merged_fails_when_open():
    def gh_get_pr(num: int) -> dict:
        return {"number": num, "state": "OPEN", "merged": False}

    result = post_action_verify.verify_pr_merged(
        17,
        {"require_merge_commit_sha": True},
        gh_get_pr=gh_get_pr,
    )
    assert result.ok is False
    assert result.failure_marker == "MERGE-STATUS: FAILED"
    assert result.next_action == "retry_merge"


def test_verify_pr_merged_passes_with_sha():
    def gh_get_pr(num: int) -> dict:
        return {"number": num, "state": "MERGED", "merged": True, "mergeCommitSha": "abc123"}

    result = post_action_verify.verify_pr_merged(
        17,
        {"require_merge_commit_sha": True},
        gh_get_pr=gh_get_pr,
    )
    assert result.ok is True


def test_unknown_marker_twice_closes_issue_as_unresolved():
    issue = _issue(
        88,
        comments=[
            "WIDGET-VERDICT: YES — first attempt",
            "WIDGET-VERDICT: YES — second time, still unresolved",
        ],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert decision.context["issue_close_reason"] == "UNRESOLVED"
    assert "stuck" in decision.context["add_labels"]


# --------------------------------------------------------------------------
# 10. Structured logging is JSON.
# --------------------------------------------------------------------------


def test_structured_logging_emits_json(capsys):
    loop_runner.configure_logging("INFO")
    loop_runner.logger.info("hello", extra={"issue": 1, "action": "triage"})
    captured = capsys.readouterr().err.strip()
    assert captured.startswith("{")
    import json

    payload = json.loads(captured)
    assert payload["message"] == "hello"
    assert payload["issue"] == 1
    assert payload["action"] == "triage"
