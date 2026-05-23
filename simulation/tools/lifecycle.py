"""Lifecycle and recovery helpers for long-running autonomous-loop work.

This module owns the "what to do when things drift over time" concerns:

- :func:`final_convergence_check` — 30-day timeout escalation.
- :func:`schedule_help_request` — emit ``HELP-REQUEST:`` after N failed
  implementation attempts.
- :func:`needs_hotfix` and :func:`hotfix_skips_design` — handle
  ``HOTFIX: #<n>`` style markers.
- :func:`cross_issue_redirect` — detect ``#<n>`` references where the
  comment was clearly meant for another issue.
- :func:`time_estimate_outlier` — reject estimates >5x the historical
  average from ``task_history.json``.
- :func:`compare_parallel_implementations` — rank parallel
  ``IMPLEMENTATION-BRANCH`` PRs by a simple rubric.
- :class:`StateHistory` and :func:`rollback_to_hash` — replay events
  back to a target state hash.
- :func:`grace_period_reopen` — reopen within 1 hour vs spawn a
  ``RECOVERY-ISSUE`` after.
- :func:`run_test_command` — execute a configurable test command and
  return pass/fail + tail of output.
"""

from __future__ import annotations

import dataclasses as _dc
import datetime as _dt
import json
import logging
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_HISTORY_PATH = REPO_ROOT / "simulation" / "data" / "task_history.json"

# ---------------------------------------------------------------------------
# 30. Final convergence check.
# ---------------------------------------------------------------------------

CONVERGENCE_TIMEOUT_DAYS = 30


def final_convergence_check(
    issue: dict[str, Any],
    *,
    now: _dt.datetime | None = None,
    timeout_days: int = CONVERGENCE_TIMEOUT_DAYS,
) -> bool:
    """True when the issue has been open >timeout_days and should escalate."""
    created = issue.get("createdAt") or issue.get("created_at")
    if not created:
        return False
    try:
        ts = _dt.datetime.fromisoformat(created.rstrip("Z")).replace(tzinfo=_dt.UTC)
    except ValueError:
        return False
    moment = now or _dt.datetime.now(tz=_dt.UTC)
    return (moment - ts).days >= timeout_days


# ---------------------------------------------------------------------------
# 15. Help request after repeated failures.
# ---------------------------------------------------------------------------

HELP_REQUEST_MARKER = "HELP-REQUEST"
HELP_NEEDED_LABEL = "help-needed"
HELP_RESPONSE_HOURS = 48
HELP_FAILED_ATTEMPT_THRESHOLD = 3


def schedule_help_request(
    failed_attempts: int,
    *,
    threshold: int = HELP_FAILED_ATTEMPT_THRESHOLD,
) -> bool:
    return failed_attempts >= threshold


def help_request_body(attempts: list[str], questions: list[str]) -> str:
    out = [f"{HELP_REQUEST_MARKER}: POSTED", ""]
    out.append("**Attempts:**")
    for attempt in attempts or ["(no attempts logged)"]:
        out.append(f"- {attempt}")
    out.append("")
    out.append("**Specific questions:**")
    for question in questions or ["What approach should we try next?"]:
        out.append(f"- {question}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 23. Hotfix workflow.
# ---------------------------------------------------------------------------

HOTFIX_RE = re.compile(r"(?im)^HOTFIX:\s*#?(?P<original>\d+)\b")


def needs_hotfix(text: str) -> int | None:
    match = HOTFIX_RE.search(text or "")
    return int(match.group("original")) if match else None


def hotfix_skips_design(text: str) -> bool:
    return needs_hotfix(text) is not None


# ---------------------------------------------------------------------------
# 18. Cross-issue redirect.
# ---------------------------------------------------------------------------

CROSS_ISSUE_RE = re.compile(r"#(\d+)")


def cross_issue_redirect(text: str, current_issue: int) -> int | None:
    """Return another issue number if the comment seems meant for it.

    Heuristic: the comment must reference exactly one ``#<n>`` total, and
    that one reference must be *different* from the current issue. If the
    comment mentions the current issue alongside others, the human is
    clearly aware of context — don't redirect.
    """
    if not text:
        return None
    nums = [int(m.group(1)) for m in CROSS_ISSUE_RE.finditer(text)]
    unique = sorted(set(nums))
    if len(unique) == 1 and unique[0] != current_issue:
        return unique[0]
    return None


# ---------------------------------------------------------------------------
# 7. Time estimation outlier.
# ---------------------------------------------------------------------------


@dataclass
class TaskHistory:
    path: Path = TASK_HISTORY_PATH

    def load(self) -> dict[str, list[float]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}
        return {k: list(v) for k, v in data.items()}

    def append(self, category: str, hours: float) -> None:
        data = self.load()
        data.setdefault(category, []).append(float(hours))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def average(self, category: str) -> float | None:
        values = self.load().get(category, [])
        if not values:
            return None
        return sum(values) / len(values)


def time_estimate_outlier(
    category: str,
    proposed_hours: float,
    *,
    multiplier: float = 5.0,
    history: TaskHistory | None = None,
) -> bool:
    history = history or TaskHistory()
    average = history.average(category)
    if average is None or average <= 0:
        return False
    return proposed_hours > average * multiplier


# ---------------------------------------------------------------------------
# 6. Parallel implementations + judge rubric.
# ---------------------------------------------------------------------------

IMPLEMENTATION_BRANCH_RE = re.compile(
    r"(?im)^IMPLEMENTATION-BRANCH:\s*(?P<branch>\S+)"
)


@dataclass
class ImplementationScore:
    branch: str
    correctness: float
    performance: float
    style: float

    @property
    def total(self) -> float:
        return 0.6 * self.correctness + 0.25 * self.performance + 0.15 * self.style


def compare_parallel_implementations(
    scores: Iterable[ImplementationScore],
) -> ImplementationScore | None:
    """Return the highest-scoring implementation or None when no candidates."""
    items = list(scores)
    if not items:
        return None
    return max(items, key=lambda s: s.total)


# ---------------------------------------------------------------------------
# 24. State history + rollback to hash.
# ---------------------------------------------------------------------------


@dataclass
class StateHistory:
    """Append-only event log per issue, used for rollback semantics."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def append(self, event: dict[str, Any]) -> None:
        self.entries.append(dict(event))

    def rollback_to(self, target_hash: str) -> "StateHistory":
        """Truncate history at the entry matching ``target_hash`` (inclusive)."""
        kept: list[dict[str, Any]] = []
        for entry in self.entries:
            kept.append(entry)
            if entry.get("state_hash") == target_hash:
                break
        if not kept or kept[-1].get("state_hash") != target_hash:
            raise ValueError(f"state hash {target_hash!r} not found in history")
        return StateHistory(entries=kept)


# ---------------------------------------------------------------------------
# 26. Reopen grace period.
# ---------------------------------------------------------------------------

REOPEN_RE = re.compile(r"(?im)^REOPEN:\s*(?P<reason>\S.*)$")
REOPEN_GRACE_MINUTES = 60


def grace_period_reopen(
    closed_at: str | None,
    reopen_comment_at: str | None,
    *,
    grace_minutes: int = REOPEN_GRACE_MINUTES,
) -> str:
    """Return ``"reopen"`` if within grace, ``"recovery"`` if past grace."""
    if not closed_at or not reopen_comment_at:
        return "recovery"
    try:
        closed = _dt.datetime.fromisoformat(closed_at.rstrip("Z")).replace(tzinfo=_dt.UTC)
        reopen = _dt.datetime.fromisoformat(reopen_comment_at.rstrip("Z")).replace(tzinfo=_dt.UTC)
    except ValueError:
        return "recovery"
    delta = (reopen - closed).total_seconds() / 60.0
    return "reopen" if 0 <= delta <= grace_minutes else "recovery"


# ---------------------------------------------------------------------------
# 22. Run-test action.
# ---------------------------------------------------------------------------


@dataclass
class TestRun:
    passed: bool
    return_code: int
    tail: str
    command: str


def run_test_command(command: str, *, timeout: int = 120) -> TestRun:
    """Execute ``command`` in a subshell, capture tail of output."""
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return TestRun(False, 124, f"TIMEOUT after {timeout}s", command)
    output = (result.stdout or "") + (result.stderr or "")
    tail = "\n".join(output.splitlines()[-40:])
    return TestRun(result.returncode == 0, result.returncode, tail, command)


# ---------------------------------------------------------------------------
# 17. Post-mortem suggestion.
# ---------------------------------------------------------------------------


@dataclass
class PostMortem:
    original_issue: int
    findings: list[str]
    optimization_title: str


def post_mortem(
    closed_issue: dict[str, Any],
    *,
    test_coverage_threshold: float = 0.7,
    complexity_threshold: int = 30,
) -> PostMortem | None:
    """Generate an optimization suggestion when closure smells inefficient."""
    findings: list[str] = []
    metrics = closed_issue.get("metrics") or {}
    coverage = float(metrics.get("test_coverage") or 0.0)
    complexity = int(metrics.get("complexity") or 0)
    if 0 < coverage < test_coverage_threshold:
        findings.append(f"test coverage is {coverage:.0%}, below {test_coverage_threshold:.0%}")
    if complexity > complexity_threshold:
        findings.append(f"complexity score {complexity} > {complexity_threshold}")
    if not findings:
        return None
    return PostMortem(
        original_issue=int(closed_issue["number"]),
        findings=findings,
        optimization_title=f"optimize: follow-up on #{closed_issue['number']}",
    )


# ---------------------------------------------------------------------------
# 12. Style guide enforcement.
# ---------------------------------------------------------------------------

STYLE_RULE_CITATION_RE = re.compile(r"(?i)\(style:\s*(?P<rule>[A-Z0-9_.-]+)\)")


def style_comment_has_citation(comment: str) -> bool:
    return bool(STYLE_RULE_CITATION_RE.search(comment or ""))


__all__ = [
    "CONVERGENCE_TIMEOUT_DAYS",
    "HELP_FAILED_ATTEMPT_THRESHOLD",
    "HELP_NEEDED_LABEL",
    "HELP_REQUEST_MARKER",
    "ImplementationScore",
    "PostMortem",
    "REOPEN_GRACE_MINUTES",
    "StateHistory",
    "TaskHistory",
    "TestRun",
    "compare_parallel_implementations",
    "cross_issue_redirect",
    "final_convergence_check",
    "grace_period_reopen",
    "help_request_body",
    "hotfix_skips_design",
    "needs_hotfix",
    "post_mortem",
    "run_test_command",
    "schedule_help_request",
    "style_comment_has_citation",
    "time_estimate_outlier",
]
