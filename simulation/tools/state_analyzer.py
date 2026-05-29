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

from datetime import datetime, timedelta, timezone
from typing import Any

from simulation.tools import config
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

    problems.sort(key=lambda p: p["priority"])
    return problems
