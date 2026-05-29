#!/usr/bin/env python3
"""Agent bridge: turn the deterministic planner into a "next action" oracle.

This is the glue between the *brain* (the Python planner) and the *hands* (an
execution agent — e.g. Claude Code running on this machine). It is **read-only**:
it inspects current repository state (live via ``gh`` or an offline ``--fixture``
JSON snapshot), runs ``analyze_state -> build_plan`` in single-step mode, and
emits the one next action's fully rendered prompt for the agent to execute.

Workflow (repeat until "no action"):

    python3 scripts/team_loop.py --repo ci4me/ai-erp-foundation
    # -> writes /tmp/next_action.md and prints persona + action + target
    # the agent reads /tmp/next_action.md, performs the work (write code, run
    # tests, post the GitHub comment/PR with the required marker), then re-runs
    # this command to get the next step.

Because the planner reads GitHub as its state store, each real action the agent
performs (a comment, an issue, a PR) changes what this command reports next —
so the loop advances itself with no hidden state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from simulation.tools.item_validator import filter_state  # noqa: E402
from simulation.tools.plan_builder import build_plan  # noqa: E402
from simulation.tools.state_analyzer import analyze_state  # noqa: E402
from simulation.tools.state_fetcher import DEFAULT_REPO, fetch_all_state  # noqa: E402

NEXT_ACTION_PATH = "/tmp/next_action.md"


def _load_fixture(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("prs", "issues", "discussions"):
        data.setdefault(key, [])
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the planner's next action for an agent.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--fixture", default=None, help="Offline JSON state snapshot.")
    parser.add_argument("--out", default=NEXT_ACTION_PATH, help="Where to write the rendered prompt.")
    args = parser.parse_args(argv)

    if args.fixture:
        print(f"📂 state: fixture {args.fixture}")
        state = _load_fixture(args.fixture)
    else:
        print(f"📡 state: live {args.repo}")
        state = fetch_all_state(args.repo)
    print(f"   {len(state['prs'])} PRs · {len(state['issues'])} issues · "
          f"{len(state['discussions'])} discussions")

    # Show what the validity/scope filter skips (for transparency); the planner
    # applies the same filter internally.
    _, skipped = filter_state(state)
    if skipped:
        print(f"⏭  {len(skipped)} item(s) skipped by the validity/scope filter:")
        for kind, number, reason in skipped[:12]:
            print(f"   - {kind} #{number}: {reason}")

    problems = analyze_state(state)
    print(f"🔍 {len(problems)} problem(s) detected:")
    for p in problems[:12]:
        t = p["target"]
        print(f"   - P{p['priority']} {p['type']} → {t['type']} #{t['number']}")

    plan = build_plan(problems, mode="single")
    if not plan["steps"]:
        print("\n✅ No actionable step — the team is idle "
              "(waiting on a human gate, or all work is done).")
        return 0

    step = plan["steps"][0]
    tgt = step["target"]
    header = (
        f"# NEXT ACTION FOR THE AGENT\n\n"
        f"- **persona:** {step['persona']}\n"
        f"- **action:** {step['action']}\n"
        f"- **target:** {tgt['type']} #{tgt['number']}\n\n"
        f"---\n\n## Rendered prompt (execute this AS the persona)\n\n"
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(header + step["body"])

    print(f"\n▶ NEXT: {step['persona']} | {step['action']} | "
          f"{tgt['type']} #{tgt['number']}")
    print(f"📄 full prompt → {args.out}")
    print("   (execute it, post the required marker, then re-run this command.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
