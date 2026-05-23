"""Top-level loop runner that wires the audit-fix modules together.

The autonomous loop has historically been driven by ``next_prompt_legacy.main``,
which picks the next action and renders the prompt. The audit added several
new responsibilities the legacy main does not own:

- acquire a per-issue lock,
- guard against cycles, timeouts, and unknown markers,
- validate the agent's output against a schema,
- verify external state actually changed,
- track per-issue retry counts as labels,
- escalate after too many failed attempts,
- log every step in a structured way.

``loop_runner`` is the orchestrator that runs *one tick* of those concerns
around a pluggable "execute action" callback. It is intentionally a thin
controller so it stays easy to test: every GitHub side-effect is injected.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from simulation.tools import lock as lock_mod
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import post_action_verify
from simulation.tools import validator

logger = logging.getLogger("autonomous_loop")

MAX_VALIDATION_RETRIES = 2  # after this many failed validations, escalate
RETRY_LABEL_PREFIX = "retry_"


# ---------------------------------------------------------------------------
# Structured logging configuration.
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit log records as one JSON object per line.

    Records can attach arbitrary structured context via ``extra={...}``. Any
    extra key that is not a standard ``LogRecord`` attribute is included in
    the JSON payload.
    """

    _RESERVED = set(logging.LogRecord("x", logging.INFO, "", 0, "", None, None).__dict__) | {
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED:
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = repr(value)
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str | int = "INFO") -> None:
    """Install the JSON formatter on the loop logger. Idempotent."""
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    handler.setLevel(level)
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False


# ---------------------------------------------------------------------------
# Retry counter (stored as labels).
# ---------------------------------------------------------------------------


def retry_count_from_labels(labels: Iterable[str], action: str) -> int:
    """Parse the retry counter for a given action out of a label set."""
    needle = f"{RETRY_LABEL_PREFIX}{action}:"
    for name in labels:
        if name.startswith(needle):
            try:
                return int(name.split(":", 1)[1])
            except ValueError:
                continue
    return 0


def bump_retry_label(
    repo: str,
    target: str,
    action: str,
    *,
    runner: lock_mod.GhRunner | None = None,
) -> int:
    """Increment the retry counter for ``action`` on ``target``. Returns new count."""
    run = runner or lock_mod._default_runner
    labels = lock_mod._list_labels(repo, target, run)
    current = retry_count_from_labels(labels, action)
    prefix = f"{RETRY_LABEL_PREFIX}{action}:"
    for name in labels:
        if name.startswith(prefix):
            lock_mod._remove_label(repo, target, name, run)
    new_count = current + 1
    lock_mod._add_label(repo, target, f"{prefix}{new_count}", run)
    return new_count


# ---------------------------------------------------------------------------
# Loop tick.
# ---------------------------------------------------------------------------


@dataclass
class TickOutcome:
    """Structured result of one loop iteration."""

    action_taken: str | None
    posted: bool
    validation: validator.ActionValidationResult | None = None
    verifications: list[post_action_verify.VerificationResult] = field(default_factory=list)
    escalation: str | None = None
    aborted: bool = False
    reason: str = ""


ActionCallback = Callable[[str, dict[str, Any]], str]
PostCallback = Callable[[str, str], None]


def run_tick(
    *,
    repo: str,
    issue: dict[str, Any],
    proposed_action: str,
    proposed_pr_number: int | None = None,
    open_prs: Iterable[dict[str, Any]] | None = None,
    execute_action: ActionCallback,
    post_to_github: PostCallback,
    gh_get_pr: post_action_verify.GhGetPr | None = None,
    gh_get_issue: post_action_verify.GhGetIssue | None = None,
    lock_runner: lock_mod.GhRunner | None = None,
    label_runner: lock_mod.GhRunner | None = None,
) -> TickOutcome:
    """Run one tick of the loop for a single issue.

    The tick is the fundamental unit of progress in the autonomous loop. It
    does the *minimum* amount of work to safely transition one issue's
    state — never more — and is designed to be re-entrant: running it twice
    in a row on the same state is a no-op thanks to the lock and the guard
    clauses.

    The 8-step protocol is:

    1. Run :func:`orch.check_locks_and_cycles`. This may override the action
       (e.g. cycle detection routes us to ``close_issue``) or abort entirely
       (lock held by another agent).
    2. Acquire the lock with a ``with`` block so it is released on any path,
       including exceptions.
    3. Execute the chosen action via the injected callback. The callback is
       where the AI runs — keeping it pluggable is what lets the test suite
       drive the full tick without needing a model.
    4. Validate the agent's output against the per-action YAML schema. This
       is the *content* check: required markers and required sections.
    5. If validation fails, post a "Validation failed" comment, bump the
       retry counter on the issue's labels, and escalate to a hard close
       once the counter exceeds :data:`MAX_VALIDATION_RETRIES`.
    6. If validation passes, run any ``post_action_checks`` declared on the
       schema. These are *external state* checks (was the PR actually
       created? actually merged?) — when one fails we transition to the
       recovery action declared by the check (e.g. ``retry_implementation``).
    7. Post the output. If validation surfaced any warnings (suspicious short
       approvals, etc.) post each one as a follow-up.
    8. Release the lock on exit.
    """
    issue_number = int(issue.get("number", 0))
    target = f"issue:{issue_number}"
    label_run = label_runner or lock_runner

    logger.info(
        "tick start",
        extra={"issue": issue_number, "proposed_action": proposed_action},
    )

    guard = orch.check_locks_and_cycles(
        repo=repo,
        issue=issue,
        proposed_action=proposed_action,
        proposed_pr_number=proposed_pr_number,
        open_prs=open_prs,
        runner=lock_runner,
    )
    if guard.abort:
        logger.warning(
            "tick aborted",
            extra={"issue": issue_number, "reason": guard.reason, "guard_context": guard.context},
        )
        return TickOutcome(action_taken=None, posted=False, aborted=True, reason=guard.reason)
    effective_action = guard.action_override or proposed_action
    effective_context = guard.context or {}
    if guard.action_override:
        logger.info(
            "guard override",
            extra={
                "issue": issue_number,
                "from": proposed_action,
                "to": guard.action_override,
                "reason": guard.reason,
            },
        )

    with lock_mod.held(repo, target, runner=lock_runner) as state:
        if not state.acquired:
            logger.warning(
                "tick aborted (lock held)",
                extra={"issue": issue_number, "reason": state.reason},
            )
            return TickOutcome(
                action_taken=None,
                posted=False,
                aborted=True,
                reason=f"lock:{state.reason}",
            )

        try:
            output_text = execute_action(effective_action, effective_context)
        except Exception as exc:  # pragma: no cover - executed by callers
            logger.exception(
                "action raised",
                extra={"issue": issue_number, "action": effective_action},
            )
            raise

        validation = validator.validate_action_output(
            effective_action, output_text, issue_context=issue
        )

        if not validation.valid:
            logger.warning(
                "validation failed",
                extra={
                    "issue": issue_number,
                    "action": effective_action,
                    "missing": validation.missing_items,
                },
            )
            post_to_github(
                target,
                "Validation failed. Missing: "
                + "; ".join(validation.missing_items)
                + ". Please correct and retry.",
            )
            new_count = bump_retry_label(repo, target, effective_action, runner=label_run)
            if new_count > MAX_VALIDATION_RETRIES:
                logger.error(
                    "escalating to UNRESOLVED",
                    extra={"issue": issue_number, "retries": new_count},
                )
                post_to_github(
                    target,
                    "Too many failed attempts — closing issue.\n\nISSUE-CLOSED: UNRESOLVED",
                )
                return TickOutcome(
                    action_taken=effective_action,
                    posted=True,
                    validation=validation,
                    escalation="close_unresolved",
                )
            return TickOutcome(
                action_taken=effective_action,
                posted=True,
                validation=validation,
                escalation=f"retry_{effective_action}:{new_count}",
            )

        schema = validator._load_schema(effective_action) or {}
        verifications = post_action_verify.run_post_action_checks(
            schema,
            issue_number=issue_number,
            pr_number=proposed_pr_number,
            open_prs=open_prs,
            gh_get_pr=gh_get_pr,
            gh_get_issue=gh_get_issue,
        )
        failed = [v for v in verifications if not v.ok]
        if failed:
            first = failed[0]
            logger.warning(
                "post-action verification failed",
                extra={
                    "issue": issue_number,
                    "action": effective_action,
                    "failure_marker": first.failure_marker,
                    "detail": first.detail,
                },
            )
            post_to_github(
                target,
                "Post-action verification failed: "
                + first.detail
                + (f"\n\n{first.failure_marker}" if first.failure_marker else ""),
            )
            return TickOutcome(
                action_taken=effective_action,
                posted=True,
                validation=validation,
                verifications=verifications,
                escalation=first.next_action,
            )

        post_to_github(target, output_text)
        for warning in validation.warnings:
            post_to_github(target, f"Warning: {warning}")

        logger.info(
            "tick complete",
            extra={"issue": issue_number, "action": effective_action},
        )
        return TickOutcome(
            action_taken=effective_action,
            posted=True,
            validation=validation,
            verifications=verifications,
        )


# ---------------------------------------------------------------------------
# Graceful shutdown helper.
# ---------------------------------------------------------------------------


def call_gh_safely(callback: Callable[[], Any], *, exit_code: int = 75) -> Any:
    """Run ``callback`` and translate API errors into a clean exit.

    The autonomous loop is invoked from cron jobs and GitHub Actions, so any
    uncaught exception should produce a non-zero exit code and a structured
    log line — *not* a stack trace that the caller cannot consume.
    """
    try:
        return callback()
    except Exception as exc:  # pragma: no cover - exercised in integration
        logger.error("gh call failed", extra={"error": repr(exc)})
        sys.exit(exit_code)


__all__ = [
    "MAX_VALIDATION_RETRIES",
    "RETRY_LABEL_PREFIX",
    "TickOutcome",
    "bump_retry_label",
    "call_gh_safely",
    "configure_logging",
    "retry_count_from_labels",
    "run_tick",
]
