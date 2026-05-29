#!/usr/bin/env python3
"""Build a fresh, empty-repo state fixture for the login-feature simulation.

Produces ``/tmp/fresh_state.json`` (override with --out): a single Discussion
carrying a ``TEAM-REQUEST`` for the login feature, no open issues, no PRs. This
is the input to ``scripts/run_planner.py --fixture`` for an offline, no-mutation
walkthrough of the full feature lifecycle.
"""

from __future__ import annotations

import argparse
import json

DEFAULT_OUT = "/tmp/fresh_state.json"

FRESH_STATE = {
    "repo": "ci4me/ai-erp-foundation",
    "prs": [],
    "issues": [],
    "discussions": [
        {
            "number": 1,
            "title": "Add a login feature",
            "body": (
                "TEAM-REQUEST: Add a login feature (email/password + OAuth) to my app.\n\n"
                "Users need to sign in with email + password and via OAuth "
                "(Google/GitHub). Sessions must be secure."
            ),
            "createdAt": "2026-05-29T00:00:00Z",
            "updatedAt": "2026-05-29T00:00:00Z",
            "url": "https://github.com/ci4me/ai-erp-foundation/discussions/1",
            "comments": [],
        }
    ],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the fresh login-feature fixture.")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output path (default: {DEFAULT_OUT}).")
    args = parser.parse_args(argv)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(FRESH_STATE, fh, indent=2)
    print(f"Wrote fresh fixture to {args.out}")
    print("  discussions: 1 (TEAM-REQUEST), issues: 0, prs: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
