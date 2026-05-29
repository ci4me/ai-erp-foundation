#!/usr/bin/env python3
"""Configuration for the autonomous planner.

The planner has two independent axes of configuration:

``mode``
    How much work a single run performs.

    - ``single`` — one run resolves exactly one problem (one persona action,
      or the first step of a chained fix). The loop then exits and must be
      re-run to observe the next state change. Small prompt, human-supervised.
    - ``multi``  — one run resolves *every* detected problem in a single
      pass (potentially many personas and many actions). Aggressive; bypasses
      the per-iteration bottleneck.

``apply``
    Whether the executor is allowed to mutate GitHub.

    - ``False`` (default) — **dry-run**. The full pipeline runs
      (fetch → analyze → build) and every step is printed, but no GitHub
      mutation is performed. Safe to run anywhere.
    - ``True`` — **apply**. Steps are executed for real (close PRs, comment,
      create PRs, review, merge, close issues).

Both axes default from environment variables but are overridable per run via
:func:`resolve` (the CLI in ``scripts/run_planner.py`` does this).

Defaulting to dry-run is a deliberate safety choice: ``multi`` mode against a
repository with dozens of marker-less issues would otherwise post dozens of
comments on the first invocation. Mutation must be opted into explicitly.
"""

from __future__ import annotations

import os
from typing import NamedTuple

VALID_MODES = ("single", "multi")

# Environment-derived defaults. These are read once at import time and act as
# the fallback when the CLI does not pass an explicit override.
PLANNER_MODE = os.getenv("PLANNER_MODE", "single").lower()
PLANNER_APPLY = os.getenv("PLANNER_APPLY", "").lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back on bad/missing values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Hours a debate may stay unresolved before the planner flags UNRESOLVED_DEBATE.
# Override with the DEBATE_RESOLUTION_TIMEOUT_HOURS environment variable.
DEBATE_RESOLUTION_TIMEOUT_HOURS = _env_int("DEBATE_RESOLUTION_TIMEOUT_HOURS", 24)

if PLANNER_MODE not in VALID_MODES:
    raise ValueError(
        f"Invalid PLANNER_MODE: {PLANNER_MODE!r}. Must be one of {VALID_MODES}."
    )


class PlannerConfig(NamedTuple):
    """Resolved configuration for a single planner run."""

    mode: str
    apply: bool

    @property
    def dry_run(self) -> bool:
        """True when no GitHub mutation should occur."""
        return not self.apply


def resolve(mode: str | None = None, apply: bool | None = None) -> PlannerConfig:
    """Resolve effective configuration, applying overrides over env defaults.

    Args:
        mode: ``"single"``/``"multi"`` to override, or ``None`` to use the
            environment default (``PLANNER_MODE``).
        apply: ``True``/``False`` to override, or ``None`` to use the
            environment default (``PLANNER_APPLY``).

    Returns:
        A :class:`PlannerConfig` with both axes resolved and validated.

    Raises:
        ValueError: if the resolved mode is not in :data:`VALID_MODES`.
    """
    resolved_mode = (mode or PLANNER_MODE).lower()
    if resolved_mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode: {resolved_mode!r}. Must be one of {VALID_MODES}."
        )
    resolved_apply = PLANNER_APPLY if apply is None else bool(apply)
    return PlannerConfig(mode=resolved_mode, apply=resolved_apply)
