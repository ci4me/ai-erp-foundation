#!/usr/bin/env python3
"""Entry point for the autonomous persona planner.

Pipeline: fetch GitHub state -> detect problems -> build a plan -> execute it.

Configuration comes from two axes (see ``simulation/tools/config.py``):

  * **mode**  — ``single`` (one action per run) or ``multi`` (all actions).
  * **apply** — mutate GitHub, or just dry-run.

Both default from environment variables (``PLANNER_MODE``, ``PLANNER_APPLY``)
and are overridable with CLI flags.

Examples::

    # Dry-run, single highest-priority action (default, safe):
    python scripts/run_planner.py

    # Dry-run, full multi-step plan:
    python scripts/run_planner.py --mode multi

    # Actually mutate the repo, one action:
    python scripts/run_planner.py --mode single --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Make the project root importable so ``simulation.tools.*`` resolves whether
# the script is run from the repo root or elsewhere.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from simulation.tools import config  # noqa: E402
from simulation.tools.debug_logger import get_logger  # noqa: E402
from simulation.tools.plan_builder import build_plan  # noqa: E402
from simulation.tools.plan_executor import execute_plan  # noqa: E402
from simulation.tools.state_analyzer import analyze_state  # noqa: E402
from simulation.tools.state_fetcher import DEFAULT_REPO, fetch_all_state  # noqa: E402

PLAN_DUMP_PATH = "/tmp/last_plan.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags, falling back to environment defaults."""
    parser = argparse.ArgumentParser(description="Autonomous persona planner.")
    parser.add_argument(
        "--mode",
        choices=config.VALID_MODES,
        default=None,
        help="single (one action/run) or multi (all actions). "
        "Default: $PLANNER_MODE or 'single'.",
    )
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        default=None,
        help="Execute steps for real (mutate GitHub).",
    )
    apply_group.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="Print the plan without mutating GitHub (default).",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Target repository owner/name (default: {DEFAULT_REPO}).",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Path to a JSON state snapshot ({prs,issues,discussions}). When set, "
        "the planner reads this instead of calling gh — fully offline. Forces "
        "dry-run unless --apply is also given.",
    )
    return parser.parse_args(argv)


def _load_fixture(path: str) -> dict:
    """Load a {prs, issues, discussions} state snapshot from JSON."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("prs", "issues", "discussions"):
        data.setdefault(key, [])
    return data


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = config.resolve(mode=args.mode, apply=args.apply)
    apply_label = "APPLY (mutating)" if cfg.apply else "DRY-RUN (safe)"

    if args.fixture:
        print(f"🚀 Planner mode={cfg.mode.upper()} | {apply_label} | fixture={args.fixture}")
        print("📂 Loading fixture state (offline)...")
        state = _load_fixture(args.fixture)
    else:
        print(f"🚀 Planner mode={cfg.mode.upper()} | {apply_label} | repo={args.repo}")
        print("📡 Fetching GitHub state...")
        state = fetch_all_state(args.repo)
    print(
        f"✅ {len(state['prs'])} PRs, {len(state['issues'])} issues, "
        f"{len(state['discussions'])} discussions"
    )

    print("🔍 Analysing problems...")
    problems = analyze_state(state)
    print(f"✅ {len(problems)} problem(s) detected")
    for p in problems[:10]:
        print(f"   - P{p['priority']} {p['type']} on {p['target']['type']} "
              f"#{p['target']['number']}")
    if len(problems) > 10:
        print(f"   ... and {len(problems) - 10} more")

    if not problems:
        print("🎉 No problems detected. Repository is healthy.")
        return 0

    print("🏗️  Building plan...")
    plan = build_plan(problems, mode=cfg.mode)
    print(f"✅ Plan built: {plan['total_steps']} step(s) (mode: {plan['mode']})")

    with open(PLAN_DUMP_PATH, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    print(f"📄 Plan written to {PLAN_DUMP_PATH}")

    # Record the whole plan as the run's step 0 so the logs/ directory captures
    # what was planned, not only what executed.
    logger = get_logger()
    logger.set_mode(plan["mode"])
    logger.log(
        persona="orchestrator",
        action="plan_built",
        target={"type": "planner", "number": ""},
        total_steps=plan["total_steps"],
        problems_detected=len(problems),
        plan_summary=plan,
        dry_run=not cfg.apply,
    )

    print("🚀 Executing plan...")
    execute_plan(plan, apply=cfg.apply, repo=args.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
