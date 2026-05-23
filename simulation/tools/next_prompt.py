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
    parse_body,
    validate_action_output,
    valid_marker_strings,
)
from simulation.tools.post_action_verify import (
    VerificationResult,
    run_post_action_checks,
    verify_issue_closed,
    verify_pr_created,
    verify_pr_merged,
)

__all__ = [
    "ActionValidationResult",
    "GuardDecision",
    "MAX_RETRIES",
    "MAX_VALIDATION_RETRIES",
    "STALE_DAYS",
    "TickOutcome",
    "VerificationResult",
    "bump_retry_label",
    "call_gh_safely",
    "check_locks_and_cycles",
    "collect_suspicious_approvals",
    "configure_logging",
    "consistency_sweep",
    "count_design_loops",
    "count_implement_loops",
    "detect_repeated_unknown_marker",
    "detect_unknown_marker",
    "is_stuck",
    "is_timed_out",
    "main",
    "parse_body",
    "retry_count_from_labels",
    "run_post_action_checks",
    "run_tick",
    "validate_action_output",
    "valid_marker_strings",
    "verify_issue_closed",
    "verify_pr_created",
    "verify_pr_merged",
    "verify_pr_exists_for_merge",
]


if __name__ == "__main__":
    sys.exit(main())
