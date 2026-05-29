#!/usr/bin/env python3
"""Deterministic problem detection over a GitHub state snapshot.

This is the pure rule engine: given the dict produced by
:func:`simulation.tools.state_fetcher.fetch_all_state`, it returns a list of
*problems*, each a dict with::

    {"type": str, "priority": int, "target": {"type": ..., "number": ...}, "data": ...}

Lower ``priority`` number = more urgent. No LLM is involved — every problem is
detected by an explicit rule, so the same state always yields the same plan.

The required-marker set (``TEAM-REQUEST:`` / ``PLAN-REQUEST:`` / ``AUDIT-ISSUE:``)
mirrors the markers the autonomous loop needs in order to triage an issue.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from simulation.tools import config
from simulation.tools.item_validator import filter_state
from simulation.tools.state_fetcher import has_request_marker

REQUIRED_ISSUE_MARKERS = ("TEAM-REQUEST:", "PLAN-REQUEST:", "AUDIT-ISSUE:")

UNREVIEWED_PR_AGE = timedelta(days=1)
STALE_DISCUSSION_AGE = timedelta(days=2)

# Markers that indicate an active design debate in a discussion thread.
DEBATE_MARKERS = ("ARGUMENT:", "COUNTER-PROPOSAL:", "REBUTTAL:", "EVIDENCE:")
# Markers that count as a debate being resolved.
DEBATE_RESOLUTION_MARKERS = ("RESOLUTION:", "DECISION-FROM-LEAD:", "CONSENSUS-REACHED:")
# Two or more objections on a PR signal a stuck review.
REVIEW_DEADLOCK_THRESHOLD = 2
# A CI-failure explanation that stays missing this long is flagged.
MISSING_EXPLANATION_AGE = timedelta(hours=1)
# Phrase the CI feedback workflow uses to request an explanation.
CI_FEEDBACK_REQUEST = "EXPLANATION:"
# Label that opts an issue/PR into automatic ADR recording.
ADR_CANDIDATE_LABEL = "adr-candidate"

# Five-phase feature lifecycle. Labels are the single source of phase truth;
# PHASE_ORDER drives the next-phase computation for the phase gate.
PHASE_LABELS = {
    "planning": "phase/planning",
    "implementation": "phase/implementation",
    "testing": "phase/testing",
    "acceptance": "phase/acceptance",
    "done": "phase/done",
}
PHASE_ORDER = ("planning", "implementation", "testing", "acceptance", "done")
# Which actions the planner may target at an issue while it is in a given phase.
# An issue with no phase label is unconstrained (legacy/non-lifecycle issues).
PHASE_ALLOWED_ACTIONS = {
    "phase/planning": {
        "decompose_feature", "comment_issue", "comment_discussion",
        "design_solution", "phase_gate", "triage_issue",
    },
    "phase/implementation": {
        "create_pr", "implement_issue", "create_sub_issues", "review_pr",
        "merge_pr", "close_issue", "phase_gate",
    },
    "phase/testing": {"run_tests", "phase_gate"},
    "phase/acceptance": {"acceptance_review", "comment_issue", "phase_gate"},
    "phase/done": set(),
}


def _texts(item: dict[str, Any]) -> list[str]:
    """All searchable text for an item: its body plus every comment body."""
    texts = [item.get("body") or ""]
    texts.extend((c.get("body") or "") for c in (item.get("comments") or []))
    return texts


def has_open_request_info(item: dict[str, Any]) -> bool:
    """True iff a ``REQUEST-INFO:`` appears with no later ``RESPONSE:``.

    Scans body then comments in order; a RESPONSE seen after a REQUEST-INFO
    clears the block.
    """
    request_open = False
    for text in _texts(item):
        if "REQUEST-INFO:" in text:
            request_open = True
        if "RESPONSE:" in text and request_open:
            request_open = False
    return request_open


def _latest_debate_ts(discussion: dict[str, Any]) -> datetime | None:
    """Timestamp of the most recent debate-bearing body/comment, or None."""
    candidates: list[datetime | None] = []
    body = discussion.get("body") or ""
    if any(marker in body for marker in DEBATE_MARKERS):
        candidates.append(_parse_ts(discussion.get("updatedAt") or discussion.get("createdAt")))
    for comment in discussion.get("comments") or []:
        cbody = comment.get("body") or ""
        if any(marker in cbody for marker in DEBATE_MARKERS):
            candidates.append(_parse_ts(comment.get("createdAt") or comment.get("updatedAt")))
    stamps = [c for c in candidates if c is not None]
    return max(stamps) if stamps else None


def has_unresolved_debate(
    discussion: dict[str, Any],
    *,
    now: datetime | None = None,
    timeout_hours: int | None = None,
) -> bool:
    """True iff a debate has gone unresolved past the configured timeout.

    A debate is *resolved* by any of ``RESOLUTION:``, ``DECISION-FROM-LEAD:``, or
    ``CONSENSUS-REACHED:`` (consensus is the preferred, stronger path). An
    unresolved debate is only flagged once its most recent debate activity is
    older than ``timeout_hours`` (default
    :data:`simulation.tools.config.DEBATE_RESOLUTION_TIMEOUT_HOURS`), giving
    personas time to converge before the planner intervenes. When no timestamp
    is available the debate is flagged conservatively.
    """
    joined = "\n".join(_texts(discussion))
    debating = any(marker in joined for marker in DEBATE_MARKERS)
    resolved = any(marker in joined for marker in DEBATE_RESOLUTION_MARKERS)
    if not debating or resolved:
        return False

    if timeout_hours is None:
        timeout_hours = config.DEBATE_RESOLUTION_TIMEOUT_HOURS
    now = now or datetime.now(timezone.utc)
    latest = _latest_debate_ts(discussion)
    if latest is None:
        return True
    return (now - latest) >= timedelta(hours=timeout_hours)


def count_objections(pr: dict[str, Any]) -> int:
    """Count ``OBJECTION:`` markers across a PR's body and comments."""
    return sum(text.count("OBJECTION:") for text in _texts(pr))


def has_missing_explanation(pr: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True iff a CI-feedback comment asked for an EXPLANATION that never came.

    Looks for a CI-feedback comment (one that *requests* ``EXPLANATION:`` — it
    contains the request phrasing) older than :data:`MISSING_EXPLANATION_AGE`,
    with no later comment that actually opens with an ``EXPLANATION:`` marker.
    """
    now = now or datetime.now(timezone.utc)
    comments = pr.get("comments") or []
    feedback_ts: datetime | None = None
    explanation_present = False
    for comment in comments:
        body = comment.get("body") or ""
        ts = _parse_ts(comment.get("createdAt") or comment.get("updatedAt"))
        is_feedback = CI_FEEDBACK_REQUEST in body and (
            "post an" in body.lower() or "ci tests failed" in body.lower()
        )
        if is_feedback:
            # Track the oldest unmet feedback request.
            if feedback_ts is None or (ts and ts < feedback_ts):
                feedback_ts = ts or feedback_ts
            continue
        # A genuine explanation is a marker line, not the request comment.
        import re as _re

        if _re.search(r"(?im)^\s*EXPLANATION:\s*\S", body):
            explanation_present = True
    if feedback_ts is None or explanation_present:
        return False
    return (now - feedback_ts) >= MISSING_EXPLANATION_AGE


def has_resolution_marker(item: dict[str, Any]) -> bool:
    """True iff the item's body/comments carry a debate-resolution marker."""
    joined = "\n".join(_texts(item))
    return any(marker in joined for marker in DEBATE_RESOLUTION_MARKERS)


def adr_already_recorded(item: dict[str, Any], prs: list[dict[str, Any]]) -> bool:
    """Heuristic: is there already an ``adr``-labeled PR referencing this item?"""
    number = item.get("number")
    for pr in prs:
        if "adr" in _labels(pr):
            haystack = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
            if f"#{number}" in haystack:
                return True
    return False


def _parse_ts(value: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp into a timezone-aware datetime.

    GitHub emits ``...Z``; :func:`datetime.fromisoformat` wants ``+00:00``.
    Returns None when the value is missing/unparseable so the caller can skip
    the age check instead of crashing.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _labels(item: dict[str, Any]) -> list[str]:
    """Normalize an item's labels to a list of label-name strings."""
    return [
        (lbl.get("name", "") if isinstance(lbl, dict) else str(lbl))
        for lbl in (item.get("labels") or [])
    ]


# -- epic decomposition + dependency tracking --------------------------------

def is_epic(issue: dict[str, Any], mode: str | None = None) -> bool:
    """True iff an issue should be treated as an epic needing decomposition.

    Gate depends on :data:`simulation.tools.config.EPIC_DETECTION_MODE`:
    ``label`` (the safe default) trusts only the ``epic`` label; ``marker`` also
    accepts a ``DECOMPOSE-REQUEST:`` body marker; ``heuristic`` also treats an
    over-long body as an epic.
    """
    mode = mode or config.EPIC_DETECTION_MODE
    if "epic" in _labels(issue):
        return True
    body = issue.get("body") or ""
    if mode in ("marker", "heuristic") and "DECOMPOSE-REQUEST:" in body:
        return True
    if mode == "heuristic" and len(body) > config.EPIC_BODY_LENGTH_THRESHOLD:
        return True
    return False


def has_decomposition_plan(issue: dict[str, Any]) -> bool:
    """True iff a DECOMPOSITION-PLAN appears in the issue body or comments."""
    return any("DECOMPOSITION-PLAN:" in text for text in _texts(issue))


def has_child_issues(state: dict[str, Any], parent_number: Any) -> bool:
    """True iff some issue links back to ``parent_number`` as its parent epic."""
    needle = f"Parent epic: #{parent_number}"
    return any(needle in (i.get("body") or "") for i in state.get("issues", []))


def _issue_by_number(state: dict[str, Any], number: int) -> dict[str, Any] | None:
    return next((i for i in state.get("issues", []) if i.get("number") == number), None)


def get_blocking_issues(state: dict[str, Any], issue: dict[str, Any]) -> list[int]:
    """Return open issues that ``issue`` declares it ``Depends on: #<n>``.

    Only blockers still present in the (open-issues) state count; a referenced
    issue that is absent is assumed closed/resolved.
    """
    blockers: list[int] = []
    for line in (issue.get("body") or "").splitlines():
        if line.strip().lower().startswith("depends on:"):
            for token in re.findall(r"#(\d+)", line):
                ref = int(token)
                ref_issue = _issue_by_number(state, ref)
                if ref_issue is not None and (ref_issue.get("state") or "open") != "closed":
                    if ref not in blockers:
                        blockers.append(ref)
    return blockers


# -- five-phase lifecycle ----------------------------------------------------

def get_current_phase(issue: dict[str, Any]) -> str | None:
    """Return the issue's ``phase/*`` label, or None if it has no phase."""
    for label in _labels(issue):
        if label.startswith("phase/"):
            return label
    return None


def _next_phase_label(current_label: str) -> str | None:
    """The label of the phase after ``current_label``, or None at the end."""
    for key, label in PHASE_LABELS.items():
        if label == current_label:
            idx = PHASE_ORDER.index(key)
            if idx + 1 < len(PHASE_ORDER):
                return PHASE_LABELS[PHASE_ORDER[idx + 1]]
            return None
    return None


def _approved(item: dict[str, Any]) -> bool:
    """True iff an ``ACCEPTANCE-DECISION: Approved`` appears in body/comments."""
    joined = "\n".join(_texts(item))
    return re.search(r"(?im)^\s*ACCEPTANCE-DECISION:\s*Approved\b", joined) is not None


def _blocked(item: dict[str, Any]) -> bool:
    """True iff an ``ACCEPTANCE-DECISION: Blocked`` appears in body/comments."""
    joined = "\n".join(_texts(item))
    return re.search(r"(?im)^\s*ACCEPTANCE-DECISION:\s*Blocked\b", joined) is not None


def latest_acceptance_decision(item: dict[str, Any]) -> str | None:
    """Return the *most recent* ACCEPTANCE-DECISION value (Approved/Blocked), or None.

    Body and comments are scanned in chronological order, so this resolves the
    rejection→rework→re-accept loop correctly: a fresh ``Approved`` after an
    earlier ``Blocked`` reads as Approved, and vice-versa.
    """
    latest: str | None = None
    for text in _texts(item):
        for m in re.finditer(
            r"(?im)^\s*ACCEPTANCE-DECISION:\s*(Approved|Blocked)\b", text
        ):
            latest = m.group(1)
    return latest


def extract_rejection_reason(item: dict[str, Any]) -> str:
    """Extract the reason text from the latest ``ACCEPTANCE-DECISION: Blocked (...)``.

    Accepts both ``Blocked (reason: ...)`` and ``Blocked (...)`` forms; returns
    "" when no parenthetical reason is given.
    """
    reason = ""
    for text in _texts(item):
        for m in re.finditer(
            r"(?im)^\s*ACCEPTANCE-DECISION:\s*Blocked\b[^\n(]*(?:\(\s*(?:reason:\s*)?([^)]*)\))?",
            text,
        ):
            if m.group(1):
                reason = m.group(1).strip()
    return reason


def rework_target_phase(reason: str | None) -> str:
    """Map a rejection reason to the phase the epic should return to.

    scope/design → planning · test/coverage/bug → testing ·
    implementation/quality/code → implementation · unclear → planning.
    """
    r = (reason or "").lower()
    if any(k in r for k in ("scope", "design", "requirement", "spec")):
        return PHASE_LABELS["planning"]
    if any(k in r for k in ("test", "coverage", "bug", "regression")):
        return PHASE_LABELS["testing"]
    if any(k in r for k in ("implement", "quality", "code", "refactor")):
        return PHASE_LABELS["implementation"]
    return PHASE_LABELS["planning"]


def _has_test_report_pass(item: dict[str, Any]) -> bool:
    joined = "\n".join(_texts(item))
    return re.search(r"(?im)^\s*TEST-REPORT:\s*Pass\b", joined) is not None


def latest_test_report(item: dict[str, Any]) -> str | None:
    """Return the *most recent* TEST-REPORT value (Pass/Fail), or None.

    Most-recent semantics mean a re-test after a fix (Pass following an earlier
    Fail) reads as Pass and gates forward, while a fresh Fail blocks the gate.
    """
    latest: str | None = None
    for text in _texts(item):
        for m in re.finditer(r"(?im)^\s*TEST-REPORT:\s*(Pass|Fail)\b", text):
            latest = m.group(1)
    return latest


def _has_approval_request(item: dict[str, Any]) -> bool:
    joined = "\n".join(_texts(item))
    return "REQUEST-APPROVAL-FROM:" in joined


def _child_issues(state: dict[str, Any], parent_number: Any) -> list[dict[str, Any]]:
    needle = f"Parent epic: #{parent_number}"
    return [i for i in state.get("issues", []) if needle in (i.get("body") or "")]


def _subtask_meets_dod(child: dict[str, Any]) -> bool:
    """Definition of Done for a sub-task: closed, has an approving review, no open objection.

    The child issue is sourced from the *open* issue list, so a sub-task still
    present here is by definition not closed yet — callers use ``has_child_issues``
    plus closed-state semantics. When a closed snapshot is supplied (state field
    set), honor it; otherwise an approving review with no objection is required.
    """
    if (child.get("state") or "open") != "closed":
        return False
    joined = "\n".join(_texts(child))
    approved = re.search(r"(?im)^\s*REVIEW-VERDICT:\s*(APPROVE|APPROVED)\b", joined)
    objection_open = "OBJECTION:" in joined and "RESOLUTION:" not in joined
    return bool(approved) and not objection_open


def implementation_complete(state: dict[str, Any], epic: dict[str, Any]) -> bool:
    """True iff every child sub-task is closed and meets its Definition of Done.

    Children that remain in the open-issue snapshot count as not-yet-closed. A
    closed child carried in a fixture (``state == 'closed'``) must also satisfy
    the DoD checks.
    """
    children = _child_issues(state, epic.get("number"))
    closed_children = state.get("closed_children") or []
    if not children and not closed_children:
        return False
    # Any open child means implementation is not complete.
    if any((c.get("state") or "open") != "closed" for c in children):
        return False
    # Every closed child (open-list with state=closed, plus explicit fixtures)
    # must meet the Definition of Done.
    candidates = [c for c in children if (c.get("state") or "open") == "closed"]
    candidates.extend(closed_children)
    return bool(candidates) and all(_subtask_meets_dod(c) for c in candidates)


def phase_gate_ready(state: dict[str, Any], epic: dict[str, Any]) -> str | None:
    """Return the next phase label iff the epic's current phase exit criteria pass.

    Exit criteria:
    - planning -> implementation: a debate resolution (CONSENSUS-REACHED/RESOLUTION)
      AND a DECOMPOSITION-PLAN AND, if an approval gate was posted, Approved.
    - implementation -> testing: implementation_complete (all children closed + DoD).
    - testing -> acceptance: TEST-REPORT: Pass.
    - acceptance -> done: ACCEPTANCE-DECISION: Approved.
    """
    current = get_current_phase(epic)
    if current is None:
        return None
    nxt = _next_phase_label(current)
    if nxt is None:
        return None

    if current == PHASE_LABELS["planning"]:
        ready = (
            has_resolution_marker(epic)
            and has_decomposition_plan(epic)
            and (not _has_approval_request(epic) or _approved(epic))
        )
    elif current == PHASE_LABELS["implementation"]:
        ready = implementation_complete(state, epic)
    elif current == PHASE_LABELS["testing"]:
        # Acceptance only when the latest report is Pass; a standing Fail blocks.
        ready = latest_test_report(epic) == "Pass"
    elif current == PHASE_LABELS["acceptance"]:
        # Done only when the *latest* decision is Approved; a standing Blocked
        # (not yet reworked) suppresses the transition.
        ready = latest_acceptance_decision(epic) == "Approved"
    else:
        ready = False
    return nxt if ready else None


def analyze_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect problems in the current GitHub state, sorted by priority.

    Rules, in priority order:

    0. ``UNANSWERED_REQUEST`` — issue/PR whose body carries a persona-request
       marker (REQUEST-REPLY-FROM / REQUEST-REVIEW-FROM / REQUEST-APPROVAL-FROM /
       QUESTION-TO). Highest priority so multi-agent conversations advance first.
    1. ``REVIEW_DEADLOCK`` — PR with >= 2 ``OBJECTION:`` markers (stuck review).
    1. ``UNANSWERED_REQUEST_INFO`` — issue with an open ``REQUEST-INFO:`` (no
       later ``RESPONSE:``); blocks progress.
    1. ``EMPTY_PR`` — open PR with no source-code files.
    2. ``MISSING_MARKER`` — open issue lacking every required marker.
    3. ``TRIVIAL_NOT_IMPLEMENTED`` — ``trivial``-labeled issue with no linked PR.
    4. ``UNREVIEWED_PR`` — PR open > 1 day with zero reviews.
    5. ``STALE_DISCUSSION`` — ``PLAN-REQUEST:`` without ``PLAN-READY:`` for > 2 days.
    5. ``UNRESOLVED_DEBATE`` — discussion with debate markers but no
       ``RESOLUTION:`` / ``DECISION-FROM-LEAD:``.

    Note: a request is flagged whenever the marker is present; the plan builder
    is responsible for skipping personas that have already replied, so an
    already-answered request yields no steps rather than re-posting.
    """
    problems: list[dict[str, Any]] = []
    # Timezone-aware "now" so comparisons against parsed (aware) timestamps
    # never raise "can't compare offset-naive and offset-aware datetimes".
    now = datetime.now(timezone.utc)

    # Validity / scope gate: drop items the loop must skip (junk labels,
    # note-only PRs) and, in focus mode, anything outside the loop:active set.
    # No-op for snapshots that use none of those labels.
    state, _skipped = filter_state(state)

    prs = state.get("prs", [])
    issues = state.get("issues", [])
    discussions = state.get("discussions", [])

    # Priority 0: unanswered persona requests (issues and PRs).
    for issue in issues:
        if has_request_marker(issue.get("body")):
            problems.append(
                {
                    "type": "UNANSWERED_REQUEST",
                    "priority": 0,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                }
            )
    for pr in prs:
        if has_request_marker(pr.get("body")):
            problems.append(
                {
                    "type": "UNANSWERED_REQUEST",
                    "priority": 0,
                    "target": {"type": "pr", "number": pr["number"]},
                    "data": pr,
                }
            )

    # Priority 1: review deadlocks (>= 2 OBJECTION markers on a PR).
    for pr in prs:
        if count_objections(pr) >= REVIEW_DEADLOCK_THRESHOLD:
            problems.append(
                {
                    "type": "REVIEW_DEADLOCK",
                    "priority": 1,
                    "target": {"type": "pr", "number": pr["number"]},
                    "data": pr,
                }
            )

    # Priority 1: issues with an open REQUEST-INFO (no RESPONSE yet).
    for issue in issues:
        if has_open_request_info(issue):
            problems.append(
                {
                    "type": "UNANSWERED_REQUEST_INFO",
                    "priority": 1,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                }
            )

    # Priority 1: empty PRs (no source-code files).
    for pr in prs:
        if not pr.get("has_code", False):
            problems.append(
                {
                    "type": "EMPTY_PR",
                    "priority": 1,
                    "target": {"type": "pr", "number": pr["number"]},
                    "data": pr,
                }
            )

    # Priority 2: issues missing every required marker.
    for issue in issues:
        body = issue.get("body") or ""
        if not any(marker in body for marker in REQUIRED_ISSUE_MARKERS):
            problems.append(
                {
                    "type": "MISSING_MARKER",
                    "priority": 2,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                }
            )

    # Priority 3: trivial issues with no linked PR (by #number in PR title).
    for issue in issues:
        if "trivial" in _labels(issue):
            linked = any(
                f"#{issue['number']}" in (pr.get("title") or "") for pr in prs
            )
            if not linked:
                problems.append(
                    {
                        "type": "TRIVIAL_NOT_IMPLEMENTED",
                        "priority": 3,
                        "target": {"type": "issue", "number": issue["number"]},
                        "data": issue,
                    }
                )

    # Priority 4: unreviewed PRs older than the threshold.
    for pr in prs:
        created = _parse_ts(pr.get("createdAt"))
        if created and created < now - UNREVIEWED_PR_AGE and not pr.get("reviews"):
            problems.append(
                {
                    "type": "UNREVIEWED_PR",
                    "priority": 4,
                    "target": {"type": "pr", "number": pr["number"]},
                    "data": pr,
                }
            )

    # Priority 5: stale plan-request discussions.
    for disc in discussions:
        body = disc.get("body") or ""
        if "PLAN-REQUEST:" in body and "PLAN-READY:" not in body:
            created = _parse_ts(disc.get("createdAt"))
            if created and created < now - STALE_DISCUSSION_AGE:
                problems.append(
                    {
                        "type": "STALE_DISCUSSION",
                        "priority": 5,
                        "target": {"type": "discussion", "number": disc["number"]},
                        "data": disc,
                    }
                )

    # Priority 1: a TEAM-REQUEST discussion with no issue created from it yet.
    # Bootstraps the lifecycle — turns a fresh human request into one issue.
    for disc in discussions:
        body = disc.get("body") or ""
        if "TEAM-REQUEST:" in body:
            link = f"From discussion #{disc['number']}"
            already = any(link in (i.get("body") or "") for i in issues)
            if not already:
                problems.append(
                    {
                        "type": "TEAM_REQUEST_UNPROCESSED",
                        "priority": 1,
                        "target": {"type": "discussion", "number": disc["number"]},
                        "data": disc,
                    }
                )

    # Priority 5: debates unresolved past the configured timeout.
    for disc in discussions:
        if has_unresolved_debate(disc, now=now):
            problems.append(
                {
                    "type": "UNRESOLVED_DEBATE",
                    "priority": 5,
                    "target": {"type": "discussion", "number": disc["number"]},
                    "data": disc,
                }
            )

    # Priority 5: CI-failure explanations that never arrived.
    for pr in prs:
        if has_missing_explanation(pr, now=now):
            problems.append(
                {
                    "type": "MISSING_EXPLANATION",
                    "priority": 5,
                    "target": {"type": "pr", "number": pr["number"]},
                    "data": pr,
                }
            )

    # Priority 5: resolved adr-candidate items with no ADR recorded yet.
    for item in [*issues, *prs]:
        if (
            ADR_CANDIDATE_LABEL in _labels(item)
            and has_resolution_marker(item)
            and not adr_already_recorded(item, prs)
        ):
            kind = "pr" if item in prs else "issue"
            problems.append(
                {
                    "type": "UNRECORDED_ADR",
                    "priority": 5,
                    "target": {"type": kind, "number": item["number"]},
                    "data": item,
                }
            )

    # Priority 3: epic decomposition lifecycle.
    for issue in issues:
        if not is_epic(issue):
            continue
        if not has_decomposition_plan(issue):
            problems.append(
                {
                    "type": "EPIC_UNDECOMPOSED",
                    "priority": 3,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                }
            )
        elif not has_child_issues(state, issue["number"]):
            problems.append(
                {
                    "type": "SUBTASKS_NOT_CREATED",
                    "priority": 3,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                }
            )

    # Priority 1: dependency blockers — informational, no corrective action.
    # The plan builder consults these to skip work on blocked issues.
    for issue in issues:
        blockers = get_blocking_issues(state, issue)
        if blockers:
            problems.append(
                {
                    "type": "BLOCKED_BY_DEPENDENCY",
                    "priority": 1,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                    "blockers": blockers,
                }
            )

    # Phase lifecycle (only issues carrying a phase/* label participate).
    for issue in issues:
        phase = get_current_phase(issue)
        if phase is None:
            continue

        # Priority 2: ready to advance to the next phase.
        nxt = phase_gate_ready(state, issue)
        if nxt is not None:
            problems.append(
                {
                    "type": "PHASE_GATE_READY",
                    "priority": 2,
                    "target": {"type": "issue", "number": issue["number"]},
                    "data": issue,
                    "current_phase": phase,
                    "next_phase": nxt,
                }
            )
            continue  # don't also raise in-phase work while a gate is pending

        # Testing phase: run tests, or follow up on a failing report.
        if phase == PHASE_LABELS["testing"]:
            report = latest_test_report(issue)
            if report is None:
                # Priority 4: no TEST-REPORT yet — run the suite.
                problems.append(
                    {
                        "type": "TESTING_REQUIRED",
                        "priority": 4,
                        "target": {"type": "issue", "number": issue["number"]},
                        "data": issue,
                    }
                )
            elif report == "Fail":
                # Priority 2: latest report is Fail — block the gate and route to
                # rework after ensuring bug sub-issues exist (G2).
                problems.append(
                    {
                        "type": "TESTING_FAILED",
                        "priority": 2,
                        "target": {"type": "issue", "number": issue["number"]},
                        "data": issue,
                    }
                )

        # Priority 3: acceptance phase needs a human approval request posted.
        if phase == PHASE_LABELS["acceptance"]:
            if latest_acceptance_decision(issue) == "Blocked":
                reason = extract_rejection_reason(issue)
                problems.append(
                    {
                        "type": "ACCEPTANCE_BLOCKED",
                        "priority": 1,
                        "target": {"type": "issue", "number": issue["number"]},
                        "data": issue,
                        "rejection_reason": reason,
                        "rework_target": rework_target_phase(reason),
                    }
                )
            elif not _has_approval_request(issue):
                problems.append(
                    {
                        "type": "ACCEPTANCE_REQUIRED",
                        "priority": 3,
                        "target": {"type": "issue", "number": issue["number"]},
                        "data": issue,
                    }
                )

    problems.sort(key=lambda p: p["priority"])
    return problems
