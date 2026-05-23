"""Post-action verification for the autonomous-loop scheduler.

The autonomous loop is built on the assumption that GitHub markers (state
transitions posted as comments) reflect *actual* GitHub state. The audit
identified a class of failure where an AI agent posts a marker like
``IMPLEMENTATION-COMPLETE: TRUE`` without actually opening a PR, or
``MERGE-STATUS: COMPLETE`` without merging. Those liars silently lock the
loop into a wrong state.

This module performs *external state checks* after an agent claims success.
It is the second line of defence after :mod:`simulation.tools.validator`:

- ``validator`` checks that the *text* the agent posted is well-formed.
- ``post_action_verify`` checks that the *world* matches what the agent
  claimed (a PR was really created, the PR was really merged, the issue
  was really closed).

Each check is a pure function that takes a small adapter callable for the
GitHub side, so the test suite can drive every code path without a network.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Outcome of one post-action check."""

    ok: bool
    failure_marker: str | None = None
    next_action: str | None = None
    detail: str = ""


GhListPrs = Callable[..., list[dict[str, Any]]]
GhGetPr = Callable[[int], dict[str, Any]]
GhGetIssue = Callable[[int], dict[str, Any]]


# ---------------------------------------------------------------------------
# PR-created check (for implement_issue / retry_implementation).
# ---------------------------------------------------------------------------


def _resolve_branch_patterns(
    params: dict[str, Any],
    issue_number: int,
) -> list[str]:
    raw = []
    if "head_branch_pattern" in params:
        raw.append(params["head_branch_pattern"])
    if "fallback_branch_pattern" in params:
        raw.append(params["fallback_branch_pattern"])
    if "head_branch" in params:
        raw.append(params["head_branch"])
    if not raw:
        raw = ["feature/issue-{{issue.number}}", "issue-{{issue.number}}"]
    return [pattern.replace("{{issue.number}}", str(issue_number)) for pattern in raw]


def verify_pr_created(
    issue_number: int,
    params: dict[str, Any],
    *,
    open_prs: Iterable[dict[str, Any]],
    now: _dt.datetime | None = None,
) -> VerificationResult:
    """Confirm that a PR matching the expected branch pattern exists.

    The check fails when no PR matches *or* when the matched PR is older than
    ``max_age_minutes`` (i.e. it predates the current run and was not created
    by this iteration).
    """
    patterns = _resolve_branch_patterns(params, issue_number)
    max_age = int(params.get("max_age_minutes") or 0)
    moment = now or _dt.datetime.now(tz=_dt.UTC)
    for pr in open_prs:
        branch = pr.get("headRefName") or pr.get("head_branch") or ""
        if branch not in patterns:
            continue
        if max_age > 0:
            created = _parse_iso(pr.get("createdAt") or pr.get("created_at"))
            if created and (moment - created).total_seconds() > max_age * 60:
                return VerificationResult(
                    ok=False,
                    failure_marker="IMPLEMENTATION-COMPLETE: FAILED",
                    next_action="retry_implementation",
                    detail=f"PR for {branch} is older than {max_age}m — predates this run",
                )
        return VerificationResult(ok=True, detail=f"PR #{pr.get('number')} on {branch}")
    return VerificationResult(
        ok=False,
        failure_marker="IMPLEMENTATION-COMPLETE: FAILED",
        next_action="retry_implementation",
        detail=f"no PR matched branch patterns: {patterns}",
    )


# ---------------------------------------------------------------------------
# PR-merged check (for merge_pr / retry_merge).
# ---------------------------------------------------------------------------


def verify_pr_merged(
    pr_number: int,
    params: dict[str, Any],
    *,
    gh_get_pr: GhGetPr,
) -> VerificationResult:
    """Confirm a PR is merged and has a merge commit SHA when required."""
    pr = gh_get_pr(pr_number)
    state = (pr.get("state") or "").upper()
    merged = pr.get("merged") or state == "MERGED"
    require_sha = bool(params.get("require_merge_commit_sha"))
    sha = pr.get("mergeCommit", {}).get("oid") if isinstance(pr.get("mergeCommit"), dict) else None
    sha = sha or pr.get("mergeCommitSha")
    if not merged:
        return VerificationResult(
            ok=False,
            failure_marker="MERGE-STATUS: FAILED",
            next_action="retry_merge",
            detail=f"PR #{pr_number} state={state}, merged=False",
        )
    if require_sha and not sha:
        return VerificationResult(
            ok=False,
            failure_marker="MERGE-STATUS: FAILED",
            next_action="retry_merge",
            detail=f"PR #{pr_number} marked merged but no merge commit SHA",
        )
    return VerificationResult(ok=True, detail=f"PR #{pr_number} merged at {sha}")


# ---------------------------------------------------------------------------
# Issue-closed check (for close_issue).
# ---------------------------------------------------------------------------


def verify_issue_closed(
    issue_number: int,
    params: dict[str, Any],
    *,
    gh_get_issue: GhGetIssue,
) -> VerificationResult:
    """Confirm the issue is actually closed after a close_issue action."""
    issue = gh_get_issue(issue_number)
    state = (issue.get("state") or "").upper()
    if state == "CLOSED":
        return VerificationResult(ok=True, detail=f"issue #{issue_number} closed")
    return VerificationResult(
        ok=False,
        failure_marker="ISSUE-STATE: STILL_OPEN",
        next_action="close_issue",
        detail=f"issue #{issue_number} expected CLOSED, got {state}",
    )


# ---------------------------------------------------------------------------
# Dispatcher.
# ---------------------------------------------------------------------------


def run_post_action_checks(
    schema: dict[str, Any],
    *,
    issue_number: int | None = None,
    pr_number: int | None = None,
    open_prs: Iterable[dict[str, Any]] | None = None,
    gh_get_pr: GhGetPr | None = None,
    gh_get_issue: GhGetIssue | None = None,
    now: _dt.datetime | None = None,
) -> list[VerificationResult]:
    """Walk every ``post_action_check`` declared on the schema and execute it."""
    results: list[VerificationResult] = []
    for check in schema.get("post_action_checks") or []:
        kind = check.get("type")
        params = check.get("params") or {}
        if kind == "pr_created":
            if issue_number is None or open_prs is None:
                raise ValueError("pr_created check needs issue_number and open_prs")
            results.append(
                verify_pr_created(
                    issue_number,
                    params,
                    open_prs=open_prs,
                    now=now,
                )
            )
        elif kind == "pr_merged":
            if pr_number is None or gh_get_pr is None:
                raise ValueError("pr_merged check needs pr_number and gh_get_pr")
            results.append(verify_pr_merged(pr_number, params, gh_get_pr=gh_get_pr))
        elif kind == "issue_closed":
            if issue_number is None or gh_get_issue is None:
                raise ValueError("issue_closed check needs issue_number and gh_get_issue")
            results.append(
                verify_issue_closed(issue_number, params, gh_get_issue=gh_get_issue)
            )
        else:
            logger.warning("unknown post_action_check type %r", kind)
    return results


def _parse_iso(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return _dt.datetime.fromisoformat(value[:-1]).replace(tzinfo=_dt.UTC)
        return _dt.datetime.fromisoformat(value)
    except ValueError:
        return None


__all__ = [
    "VerificationResult",
    "run_post_action_checks",
    "verify_issue_closed",
    "verify_pr_created",
    "verify_pr_merged",
]
