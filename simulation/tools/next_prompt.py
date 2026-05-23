"""CLI entrypoint and public surface for the autonomous-loop scheduler.

This module is intentionally tiny: it dispatches to the legacy CLI for
backward compatibility (``python -m simulation.tools.next_prompt``) and
re-exports the audit-fix primitives so callers have one stable import point.

The audit fixes are implemented in companion modules:

- :mod:`simulation.tools.validator` — strengthened marker parsing and
  per-action output schema validation.
- :mod:`simulation.tools.lock` — GitHub-label-based concurrency lock so
  multiple loop instances cannot stomp on the same issue.
- :mod:`simulation.tools.next_prompt_orchestrator` — guard clauses for
  cycles, timeouts, unknown markers, missing PRs, and the consistency
  sweep.
- :mod:`simulation.tools.post_action_verify` — external-state checks that
  confirm the world matches what an agent claimed.
- :mod:`simulation.tools.loop_runner` — the small orchestrator that wires
  everything together for one loop tick, including structured logging and
  retry-counter labels.

The thin re-export surface lets the rest of the codebase keep importing
``from simulation.tools.next_prompt import ...`` without knowing which
companion module owns each helper.
"""

from __future__ import annotations

import sys

from simulation.tools.next_prompt_cli import main
from simulation.tools.next_prompt_orchestrator import (
    MAX_RETRIES,
    STALE_DAYS,
    GuardDecision,
    check_locks_and_cycles,
    collect_suspicious_approvals,
    consistency_sweep,
    count_design_loops,
    count_implement_loops,
    detect_unknown_marker,
    is_stuck,
    is_timed_out,
    verify_pr_exists_for_merge,
)
from simulation.tools.loop_runner import (
    MAX_VALIDATION_RETRIES,
    TickOutcome,
    bump_retry_label,
    call_gh_safely,
    configure_logging,
    retry_count_from_labels,
    run_tick,
)
from simulation.tools.validator import (
    ActionValidationResult,
    detect_repeated_unknown_marker,
    extract_markers,
    parse_body,
    validate_action_output,
    valid_marker_strings,
)
from simulation.tools.optimization import (
    classify_intent,
    detect_identical_feedback,
    detect_off_topic,
    extract_markers_priority,
    feedback_hash,
    is_stale_clarification,
    is_style_only_review,
    output_doubled,
    quick_fix_bypass,
    should_auto_approve_style,
    should_break_loop,
    state_hash,
    style_round_count,
    truncate_history,
)
from simulation.tools.decision_log import (
    DecisionLog,
    parse_issue_body as parse_decision_log,
    write_to_body as write_decision_log,
)
from simulation.tools.deliberation import (
    ConflictLog,
    Debate,
    QuorumStatus,
    VoteTally,
    apply_retraction,
    detect_bypass,
    detect_retraction,
    log_bypass,
    pause_state,
    peer_consensus_blocker,
    quorum_status,
    tally_counterproposals,
    tally_votes,
)
from simulation.tools.safety import (
    ConstraintSet,
    EthicsVerdict,
    KnowledgeScore,
    ethics_check,
    extract_rationale,
    is_dangerous,
    is_force_acknowledged,
    needs_sentiment_clarification,
    requires_rationale,
    sentiment_clarification_template,
)
from simulation.tools.lifecycle import (
    ImplementationScore,
    PostMortem,
    StateHistory,
    TaskHistory,
    TestRun,
    compare_parallel_implementations,
    cross_issue_redirect,
    final_convergence_check,
    grace_period_reopen,
    help_request_body,
    hotfix_skips_design,
    needs_hotfix,
    post_mortem,
    run_test_command,
    schedule_help_request,
    style_comment_has_citation,
    time_estimate_outlier,
)
from simulation.tools.post_action_verify import (
    VerificationResult,
    run_post_action_checks,
    verify_issue_closed,
    verify_pr_created,
    verify_pr_merged,
)
from simulation.tools.lesson_repository import (
    DEFAULT_LESSONS_DIR,
    Lesson,
    LessonRepository,
)
from simulation.tools.lesson_injector import LessonInjector
from simulation.tools.retrospective import Retrospective


def enhance_prompt_with_lessons(
    *,
    action_prompt: str,
    issue_title: str = "",
    issue_body: str = "",
    storage_path: str | None = None,
) -> str:
    """Inject the top relevant lessons into ``action_prompt`` (no-op if none).

    Disabled by setting ``LEARNING_ENABLED=false`` in the environment so
    operators can turn the sidecar off without code changes.
    """
    import os as _os

    if _os.environ.get("LEARNING_ENABLED", "true").lower() == "false":
        return action_prompt
    return LessonInjector(storage_path=storage_path).enhance_prompt(
        original_prompt=action_prompt,
        issue_title=issue_title,
        issue_body=issue_body,
    )


__all__ = [
    "ActionValidationResult",
    "DEFAULT_LESSONS_DIR",
    "DecisionLog",
    "GuardDecision",
    "Lesson",
    "LessonInjector",
    "LessonRepository",
    "Retrospective",
    "enhance_prompt_with_lessons",
    "MAX_RETRIES",
    "MAX_VALIDATION_RETRIES",
    "STALE_DAYS",
    "TickOutcome",
    "VerificationResult",
    "bump_retry_label",
    "call_gh_safely",
    "check_locks_and_cycles",
    "classify_intent",
    "collect_suspicious_approvals",
    "configure_logging",
    "consistency_sweep",
    "count_design_loops",
    "count_implement_loops",
    "detect_identical_feedback",
    "detect_off_topic",
    "detect_repeated_unknown_marker",
    "detect_unknown_marker",
    "extract_markers",
    "extract_markers_priority",
    "feedback_hash",
    "is_stale_clarification",
    "is_stuck",
    "is_style_only_review",
    "is_timed_out",
    "main",
    "output_doubled",
    "parse_body",
    "parse_decision_log",
    "quick_fix_bypass",
    "retry_count_from_labels",
    "run_post_action_checks",
    "run_tick",
    "should_auto_approve_style",
    "should_break_loop",
    "state_hash",
    "style_round_count",
    "truncate_history",
    "validate_action_output",
    "valid_marker_strings",
    "verify_issue_closed",
    "verify_pr_created",
    "verify_pr_merged",
    "verify_pr_exists_for_merge",
    "write_decision_log",
]


if __name__ == "__main__":
    sys.exit(main())
