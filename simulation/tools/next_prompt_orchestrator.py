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

from simulation.tools import decision_log
from simulation.tools import deliberation
from simulation.tools import lifecycle
from simulation.tools import lock as lock_mod
from simulation.tools import optimization
from simulation.tools import loop_speedup
from simulation.tools import safety
from simulation.tools import validator

logger = logging.getLogger(__name__)

# Process-local dedupe + stall caches. Each fresh CLI invocation gets a
# fresh cache, which is exactly how the loop runs in production.
DEDUPE_CACHE = loop_speedup.DedupeCache()
STALL_TRACKER = loop_speedup.StallTracker()

MAX_RETRIES = 3
STALE_DAYS = 7
COT_REPEAT_SIMILARITY = 0.85
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
    full_text = (issue.get("body") or "") + "\n" + "\n".join(
        (c.get("body") or "") for c in (issue.get("comments") or [])
    )

    # 0a. Ethics check trumps everything.
    verdict = safety.ethics_check(full_text)
    if verdict.triggered and not verdict.has_override:
        return GuardDecision(
            action_override="post_status_and_exit",
            reason=f"ethics:{','.join(verdict.matched)}",
            context={
                "marker": "LOOP-STATUS: BLOCKED",
                "ethics_violation": True,
                "matched_keywords": verdict.matched,
                "needs_label": "ethics-review",
            },
        )

    # 0b. Dangerous keyword from human comment without FORCE: YES.
    dangerous, matched_dangerous = safety.is_dangerous(full_text)
    if dangerous and not safety.is_force_acknowledged(full_text):
        return GuardDecision(
            action_override="post_status_and_exit",
            reason=f"dangerous:{','.join(matched_dangerous)}",
            context={
                "marker": "LOOP-STATUS: BLOCKED",
                "needs_force_ack": True,
                "matched_keywords": matched_dangerous,
            },
        )

    # 0c. Pause overrides every action while active.
    paused, pause_reason = deliberation.pause_state(issue)
    if paused:
        return GuardDecision(
            abort=True,
            reason=f"paused:{pause_reason}",
            context={"add_labels": [deliberation.PAUSE_LABEL]},
        )

    # 0d. 30-day convergence escalation.
    if lifecycle.final_convergence_check(issue, now=now):
        return GuardDecision(
            action_override="open_followup_issue",
            reason="convergence_30d",
            context={
                "escalate_to_human": True,
                "needs_label": "human-escalation",
                "summary_of_attempts": True,
            },
        )

    # 0e. CoT repetition loop-breaker.
    cot_entries = decision_log.parse_cot_entries(issue.get("body") or "")
    if len(cot_entries) >= 2:
        sim = deliberation.jaccard_similarity(cot_entries[-1].content, cot_entries[-2].content)
        if sim >= COT_REPEAT_SIMILARITY and not has_progress(issue):
            return GuardDecision(
                action_override="close_issue",
                reason=f"cot_repeat:{sim:.2f}",
                context={
                    "issue_close_reason": "UNRESOLVED",
                    "marker": "ISSUE-CLOSED: UNRESOLVED",
                    "add_labels": ["stuck-reasoning"],
                    "close_comment": (
                        f"SYSTEM: Repeated reasoning detected (similarity {sim:.2%}). "
                        "Looping – escalating to human."
                    ),
                },
            )

    # 0f. Auto-apply policy labels before any other decision so that
    # subsequent guards see the labels the human implied (risk:high etc).
    missing_labels = loop_speedup.infer_policy_labels(issue)
    if missing_labels:
        labels = (issue.get("labels") or []) + [{"name": label} for label in missing_labels]
        issue["labels"] = labels  # in-place: cheap and the orchestrator owns this dict

    # 0g. Stall detection: same hash twice in a row → skip this issue.
    should_skip, stall = STALL_TRACKER.observe(issue)
    if should_skip:
        return GuardDecision(
            abort=True,
            reason=f"stalled:{stall}",
            context={"add_labels": ["stalled"], "stall_count": stall},
        )

    # 0h. Dedupe: refuse to repeat the same (persona, target, action) within window.
    persona_id = (issue.get("persona_id") or "").strip() or "unknown"
    target_id = issue.get("number", 0)
    if DEDUPE_CACHE.is_duplicate(persona_id, target_id, proposed_action):
        return GuardDecision(
            abort=True,
            reason=f"dedupe:{persona_id}:{target_id}:{proposed_action}",
        )

    # 1. Quick-fix bypass for trivial TEAM-REQUESTs.
    if proposed_action in {"triage_issue", "design_solution"} and optimization.quick_fix_bypass(issue):
        return GuardDecision(
            action_override="implement_issue",
            reason="quick_fix_bypass",
            context={"quick_fix": True},
        )

    # 2. Stale awaiting-human → close as INACTIVE.
    if optimization.is_stale_clarification(issue, now=now):
        return GuardDecision(
            action_override="close_issue",
            reason="stale_clarification",
            context={
                "issue_close_reason": "INACTIVE",
                "marker": "ISSUE-CLOSED: INACTIVE",
            },
        )

    # 3. State-hash loop breaker.
    labels = {label.get("name", "") for label in issue.get("labels") or []}
    if optimization.should_break_loop(optimization.stuck_count(labels)):
        return GuardDecision(
            action_override="close_issue",
            reason="state_hash_stuck",
            context={
                "issue_close_reason": "UNRESOLVED",
                "marker": "ISSUE-CLOSED: UNRESOLVED",
                "add_labels": ["circular-loop"],
            },
        )

    # 4. Identical-feedback cycle breaker — only when nothing else moved.
    feedback_bodies = [
        c.get("body") or ""
        for c in (issue.get("comments") or [])
        if "REQUEST_CHANGES" in (c.get("body") or "") or "REJECT" in (c.get("body") or "")
    ]
    if optimization.detect_identical_feedback(feedback_bodies) and not has_progress(issue):
        return GuardDecision(
            action_override="close_issue",
            reason="identical_feedback",
            context={
                "issue_close_reason": "UNRESOLVED",
                "marker": "ISSUE-CLOSED: UNRESOLVED",
                "close_comment": "Identical feedback repeated – human intervention required.",
            },
        )

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
