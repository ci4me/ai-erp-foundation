"""Audit-fix orchestrator for the autonomous loop.

This module sits between the scheduler in ``next_prompt_legacy`` and the
GitHub state. It does not own the prompt rendering — it owns the *guard
clauses* that the audit identified as missing:

1. Cycle detection (design / implementation loops) with ``MAX_RETRIES``.
2. Stuck / unresolved auto-close after the retry budget is exhausted.
3. Timeout auto-close for issues parked in ``DEFER`` or ``wait_for_human``
   for more than ``STALE_DAYS``.
4. Unknown-marker → ``request_clarification`` routing.
5. Missing-PR handling on ``merge_pr``.
6. Consistency check sweep across merged PRs, open issues, and approvals.
7. Lock check (via ``simulation.tools.lock``) before any mutation.

All entry points are pure functions that accept *state dictionaries* so the
test suite can drive them without GitHub. ``next_prompt_legacy.resolve_priority``
calls into ``check_locks_and_cycles`` before returning an action.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from simulation.tools import lock as lock_mod
from simulation.tools import validator

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
STALE_DAYS = 7
DEFER_MARKER_RE = re.compile(r"(?im)^TRIAGE-DECISION:\s*DEFER\b")
WAIT_FOR_HUMAN_LABELS = frozenset({"wait_for_human", "wait-for-human", "needs-human"})
DESIGN_LOOP_MARKER_RE = re.compile(r"(?im)^DESIGN-APPROVAL:\s*REQUEST_CHANGES\b")
IMPL_LOOP_MARKER_RE = re.compile(r"(?im)^IMPLEMENTATION-COMPLETE:\s*(FALSE|FAILED)\b")
APPROVE_MARKER_RE = re.compile(r"(?im)^REVIEW-VERDICT:\s*APPROVE(?:_WITH_CONDITIONS)?\b")
DONE_MARKER_RE = re.compile(r"(?im)^ISSUE-CLOSED:\s*DONE\b")
MERGE_COMPLETE_RE = re.compile(r"(?im)^MERGE-STATUS:\s*COMPLETE\b")


@dataclass
class GuardDecision:
    """The orchestrator's verdict for one issue or PR.

    ``action_override`` is the action id the scheduler must run instead of
    the priority-list winner. When ``None``, the regular scheduler runs.
    """

    action_override: str | None = None
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    abort: bool = False


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.UTC)


def _parse_iso(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return _dt.datetime.fromisoformat(value[:-1]).replace(tzinfo=_dt.UTC)
        return _dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _issue_body_and_comments(issue: dict[str, Any]) -> str:
    parts = [issue.get("body") or ""]
    for comment in issue.get("comments") or []:
        parts.append(comment.get("body") or "")
    return "\n\n".join(parts)


def _labels(issue: dict[str, Any]) -> set[str]:
    return {label.get("name", "") for label in issue.get("labels") or []}


# ---------------------------------------------------------------------------
# Cycle detection.
# ---------------------------------------------------------------------------


def count_design_loops(issue: dict[str, Any]) -> int:
    body = _issue_body_and_comments(issue)
    return len(DESIGN_LOOP_MARKER_RE.findall(body))


def count_implement_loops(issue: dict[str, Any]) -> int:
    body = _issue_body_and_comments(issue)
    return len(IMPL_LOOP_MARKER_RE.findall(body))


def has_progress(issue: dict[str, Any]) -> bool:
    body = _issue_body_and_comments(issue)
    return bool(APPROVE_MARKER_RE.search(body) or MERGE_COMPLETE_RE.search(body))


def is_stuck(issue: dict[str, Any], *, max_retries: int = MAX_RETRIES) -> tuple[bool, str]:
    """Return (stuck?, reason). Stuck = any loop counter exceeds the budget."""
    design = count_design_loops(issue)
    impl = count_implement_loops(issue)
    if has_progress(issue):
        return False, ""
    if design > max_retries:
        return True, f"design_loop_count={design} > {max_retries}"
    if impl > max_retries:
        return True, f"implement_loop_count={impl} > {max_retries}"
    return False, ""


# ---------------------------------------------------------------------------
# Timeout detection.
# ---------------------------------------------------------------------------


def is_timed_out(
    issue: dict[str, Any],
    *,
    now: _dt.datetime | None = None,
    stale_days: int = STALE_DAYS,
) -> tuple[bool, str]:
    """Issues parked in DEFER or wait_for_human for >stale_days are timed out."""
    body = _issue_body_and_comments(issue)
    labels = _labels(issue)
    parked_for_human = bool(WAIT_FOR_HUMAN_LABELS & labels)
    parked_deferred = bool(DEFER_MARKER_RE.search(body))
    if not (parked_for_human or parked_deferred):
        return False, ""
    updated = _parse_iso(issue.get("updatedAt") or issue.get("updated_at"))
    if updated is None:
        return False, ""
    age = (now or _now_utc()) - updated
    if age.days >= stale_days:
        why = "DEFER" if parked_deferred else "wait_for_human"
        return True, f"parked {age.days}d in {why}"
    return False, ""


# ---------------------------------------------------------------------------
# Unknown-marker routing.
# ---------------------------------------------------------------------------


def detect_unknown_marker(issue: dict[str, Any]) -> validator.UnknownMarker | None:
    """Return the first unknown marker observed in body or comments, or None."""
    bodies: list[str] = [issue.get("body") or ""]
    for comment in issue.get("comments") or []:
        bodies.append(comment.get("body") or "")
    results = [validator.parse_body(body) for body in bodies if body]
    return validator.first_unknown_marker(results)


def unknown_marker_repeat_counts(issue: dict[str, Any]) -> dict[str, int]:
    """Count how many times each unknown marker token appears on this issue."""
    bodies: list[str] = [issue.get("body") or ""]
    for comment in issue.get("comments") or []:
        bodies.append(comment.get("body") or "")
    return validator.detect_repeated_unknown_marker(bodies)


# ---------------------------------------------------------------------------
# Consistency sweep.
# ---------------------------------------------------------------------------


@dataclass
class ConsistencyFinding:
    classification: str
    issue_number: int | None
    pr_number: int | None
    detail: str


def consistency_sweep(
    *,
    open_issues: Iterable[dict[str, Any]],
    open_prs: Iterable[dict[str, Any]],
    merged_prs: Iterable[dict[str, Any]],
) -> list[ConsistencyFinding]:
    findings: list[ConsistencyFinding] = []
    open_issue_numbers = {int(issue["number"]): issue for issue in open_issues}
    open_pr_numbers = {int(pr["number"]) for pr in open_prs}
    open_pr_by_issue: dict[int, set[int]] = {}
    for pr in open_prs:
        for ref in pr.get("closingIssuesReferences") or []:
            ref_no = ref.get("number") if isinstance(ref, dict) else None
            if ref_no is None:
                continue
            open_pr_by_issue.setdefault(int(ref_no), set()).add(int(pr["number"]))

    # Class 1: PR merged but linked issue still open.
    for pr in merged_prs:
        for ref in pr.get("closingIssuesReferences") or []:
            ref_no = ref.get("number") if isinstance(ref, dict) else None
            if ref_no is None:
                continue
            if int(ref_no) in open_issue_numbers:
                findings.append(
                    ConsistencyFinding(
                        classification="merged_pr_open_issue",
                        issue_number=int(ref_no),
                        pr_number=int(pr["number"]),
                        detail=f"PR #{pr['number']} merged but issue #{ref_no} still open",
                    )
                )

    # Class 2: ISSUE-CLOSED: DONE in body/comments but the issue is still open.
    for issue_no, issue in open_issue_numbers.items():
        body = _issue_body_and_comments(issue)
        if DONE_MARKER_RE.search(body):
            findings.append(
                ConsistencyFinding(
                    classification="done_marker_still_open",
                    issue_number=issue_no,
                    pr_number=None,
                    detail="ISSUE-CLOSED: DONE marker present but issue is open",
                )
            )

    # Class 3: REVIEW-VERDICT: APPROVE present but no open PR for the issue.
    for issue_no, issue in open_issue_numbers.items():
        body = _issue_body_and_comments(issue)
        if not APPROVE_MARKER_RE.search(body):
            continue
        if open_pr_by_issue.get(issue_no):
            continue
        # The approval was on a PR that has been closed — there is no live PR
        # tied to this issue and no merged PR either; treat as "PR missing".
        if not _approve_traces_a_merged_pr(issue_no, merged_prs):
            findings.append(
                ConsistencyFinding(
                    classification="approve_no_pr",
                    issue_number=issue_no,
                    pr_number=None,
                    detail="REVIEW-VERDICT: APPROVE but no open PR — PR missing",
                )
            )

    return findings


def _approve_traces_a_merged_pr(issue_no: int, merged_prs: Iterable[dict[str, Any]]) -> bool:
    for pr in merged_prs:
        for ref in pr.get("closingIssuesReferences") or []:
            if isinstance(ref, dict) and int(ref.get("number", 0)) == issue_no:
                return True
    return False


# ---------------------------------------------------------------------------
# Missing-PR guard on merge_pr.
# ---------------------------------------------------------------------------


def verify_pr_exists_for_merge(
    pr_number: int,
    open_prs: Iterable[dict[str, Any]],
) -> tuple[bool, str]:
    """Confirm the PR is still open before attempting to merge."""
    for pr in open_prs:
        if int(pr.get("number", -1)) == pr_number:
            state = pr.get("state", "OPEN").upper()
            if state == "OPEN":
                return True, ""
            return False, f"PR #{pr_number} is {state}"
    return False, f"PR #{pr_number} not found"


# ---------------------------------------------------------------------------
# Top-level guard used by next_prompt_legacy.
# ---------------------------------------------------------------------------


def check_locks_and_cycles(
    *,
    repo: str,
    issue: dict[str, Any],
    proposed_action: str,
    proposed_pr_number: int | None = None,
    open_prs: Iterable[dict[str, Any]] | None = None,
    runner: lock_mod.GhRunner | None = None,
    now: _dt.datetime | None = None,
    max_retries: int = MAX_RETRIES,
    stale_days: int = STALE_DAYS,
) -> GuardDecision:
    """Inspect ``issue`` and return how the scheduler should react.

    Order of checks matters — each returns early, so a more serious problem
    pre-empts a less serious one:

      1. Stuck loop → close with ``ISSUE-CLOSED: UNRESOLVED`` and label
         ``stuck``. A stuck issue cannot benefit from another retry; the
         budget is intentionally tight to keep humans in the loop.
      2. Timeout → close with ``ISSUE-CLOSED: TIMEOUT``. Defer / wait-for-
         human states are temporary by design; after :data:`STALE_DAYS` we
         assume the human is not coming back and free the slot.
      3. Unknown marker → ``request_clarification`` (or close-as-unresolved
         if the same unknown marker repeated). The loop never silently drops
         a signal it cannot parse.
      4. ``merge_pr`` against a missing PR → ``close_issue``. A merge action
         that points at a missing PR is almost always a data drift and we
         prefer closing the issue over crashing inside ``gh pr merge``.
      5. Lock held by another agent → abort. Concurrent mutation is the
         root cause of most state inconsistencies; we'd rather lose a tick
         than corrupt the issue.
    """
    issue_number = int(issue.get("number", 0))

    stuck, why = is_stuck(issue, max_retries=max_retries)
    if stuck:
        return GuardDecision(
            action_override="close_issue",
            reason=f"cycle:{why}",
            context={
                "issue_close_reason": "UNRESOLVED",
                "add_labels": ["stuck"],
                "marker": "ISSUE-CLOSED: UNRESOLVED",
            },
        )

    timed_out, why = is_timed_out(issue, now=now, stale_days=stale_days)
    if timed_out:
        return GuardDecision(
            action_override="close_issue",
            reason=f"timeout:{why}",
            context={
                "issue_close_reason": "TIMEOUT",
                "marker": "ISSUE-CLOSED: TIMEOUT",
            },
        )

    unknown = detect_unknown_marker(issue)
    if unknown is not None:
        repeats = unknown_marker_repeat_counts(issue)
        if repeats.get(unknown.token, 0) >= 2:
            return GuardDecision(
                action_override="close_issue",
                reason=f"unknown_marker_repeated:{unknown.token}",
                context={
                    "issue_close_reason": "UNRESOLVED",
                    "marker": "ISSUE-CLOSED: UNRESOLVED",
                    "add_labels": ["stuck"],
                    "close_comment": (
                        f"Unknown marker '{unknown.token}' appeared "
                        f"{repeats[unknown.token]} times without correction."
                    ),
                },
            )
        return GuardDecision(
            action_override="request_clarification",
            reason=f"unknown_marker:{unknown.token}",
            context={
                "unknown_marker": unknown.token,
                "unknown_marker_location": (
                    f"line {unknown.line_number}: {unknown.raw_line.strip()}"
                ),
                "valid_markers": ", ".join(validator.valid_marker_strings()),
            },
        )

    if proposed_action == "merge_pr" and proposed_pr_number is not None:
        ok, reason = verify_pr_exists_for_merge(proposed_pr_number, open_prs or [])
        if not ok:
            return GuardDecision(
                action_override="close_issue",
                reason=f"missing_pr:{reason}",
                context={
                    "issue_close_reason": "REJECTED",
                    "marker": "ISSUE-CLOSED: REJECTED",
                    "close_comment": f"PR not found: {reason}",
                },
            )

    target = f"issue:{issue_number}"
    if lock_mod.is_locked(repo, target, runner=runner):
        return GuardDecision(
            abort=True,
            reason="locked",
            context={"target": target},
        )

    return GuardDecision()


# ---------------------------------------------------------------------------
# Suspicious approval helper (delegates to validator).
# ---------------------------------------------------------------------------


def collect_suspicious_approvals(issue: dict[str, Any]) -> list[validator.MarkerHit]:
    """Return suspicious approval markers from this issue's comments."""
    suspicious: list[validator.MarkerHit] = []
    for comment in issue.get("comments") or []:
        body = comment.get("body") or ""
        result = validator.parse_body(body, comment_length=len(body))
        for hit in result.hits:
            if hit.suspicious:
                suspicious.append(hit)
    return suspicious


__all__ = [
    "GuardDecision",
    "MAX_RETRIES",
    "STALE_DAYS",
    "check_locks_and_cycles",
    "collect_suspicious_approvals",
    "consistency_sweep",
    "count_design_loops",
    "count_implement_loops",
    "detect_unknown_marker",
    "has_progress",
    "is_stuck",
    "is_timed_out",
    "unknown_marker_repeat_counts",
    "verify_pr_exists_for_merge",
]
