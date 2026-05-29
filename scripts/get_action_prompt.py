#!/usr/bin/env python3
"""Render the authentic prompt for a specific action+issue from the PY pipeline.

``next_prompt`` always picks the single highest-priority action across the whole
repo. When you want the prompt for a *specific* action on a *specific* issue
(e.g. the implementation prompt for one ready feature, while unrelated PRs sit
ahead in the priority queue), this renders it through the same
``render_prompt`` machinery the loop uses — so the output is identical to what
the system would emit when that action reaches the front of the queue.

    python3 scripts/get_action_prompt.py --action implement_issue --issue 179
    # -> writes /tmp/next_action.md
"""

from __future__ import annotations

import argparse
import sys

from simulation.tools.next_prompt_legacy import gather_repo_state, render_prompt

DEFAULT_REPO = "ci4me/ai-erp-foundation"
OUT = "/tmp/next_action.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a specific action's prompt.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--action", default="implement_issue")
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)

    state = gather_repo_state(args.repo)
    issue = next((i for i in state.open_issues if i.get("number") == args.issue), None)
    if issue is None:
        print(f"ERROR: issue #{args.issue} not found in open issues.", file=sys.stderr)
        return 2

    prompt = render_prompt(
        args.repo, args.action, {"issue": issue}, state, post_mode="dry-run"
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(prompt)
    print(f"Rendered '{args.action}' prompt for issue #{args.issue} → {args.out}")
    print(f"({len(prompt)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
