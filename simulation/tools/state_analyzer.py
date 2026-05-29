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

from simulation.tools.state_fetcher import has_request_marker

REQUIRED_ISSUE_MARKERS = ("TEAM-REQUEST:", "PLAN-REQUEST:", "AUDIT-ISSUE:")

UNREVIEWED_PR_AGE = timedelta(days=1)
STALE_DISCUSSION_AGE = timedelta(days=2)


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
    1. ``EMPTY_PR`` — open PR with no source-code files.
    2. ``MISSING_MARKER`` — open issue lacking every required marker.
    3. ``TRIVIAL_NOT_IMPLEMENTED`` — ``trivial``-labeled issue with no linked PR.
    4. ``UNREVIEWED_PR`` — PR open > 1 day with zero reviews.
    5. ``STALE_DISCUSSION`` — ``PLAN-REQUEST:`` without ``PLAN-READY:`` for > 2 days.

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

    problems.sort(key=lambda p: p["priority"])
    return problems
