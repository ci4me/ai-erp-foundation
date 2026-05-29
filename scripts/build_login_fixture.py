#!/usr/bin/env python3
"""Build the initial state fixture for the login-feature **dry-run** simulation.

Produces ``/tmp/login_fixture.json`` (override with ``--out``): a single
Discussion carrying the ``TEAM-REQUEST`` for a login feature, with **no** open
issues and **no** PRs, plus the minimal repo metadata the state layer needs.

This fixture is the sole input to the offline walkthrough — the planner reads it
via ``scripts/run_planner.py --fixture`` and never touches the live GitHub API.
Nothing here mutates a remote: it only writes a local JSON file.

Usage::

    python3 scripts/build_login_fixture.py            # -> /tmp/login_fixture.json
    python3 scripts/build_login_fixture.py --out x.json
"""

from __future__ import annotations

import argparse
import json

DEFAULT_OUT = "/tmp/login_fixture.json"

# The exact request body the simulation begins from. ``TEAM-REQUEST:`` is the
# marker the planner's state analyzer keys on to detect an unprocessed request.
TEAM_REQUEST_BODY = "TEAM-REQUEST: Add a login feature (email/password + OAuth) to my app."

# Minimal repo metadata consumed by the state layer (owner / name / default
# branch). ``repo`` as "owner/name" is what run_planner/state_fetcher expect;
# the structured block is carried alongside for any consumer that wants it.
LOGIN_FIXTURE = {
    "repo": "ci4me/ai-erp-foundation",
    "repo_meta": {
        "owner": "ci4me",
        "name": "ai-erp-foundation",
        "defaultBranch": "main",
    },
    "prs": [],
    "issues": [],
    "discussions": [
        {
            "number": 1,
            "title": "Add a login feature",
            "body": TEAM_REQUEST_BODY,
            "createdAt": "2026-05-29T00:00:00Z",
            "updatedAt": "2026-05-29T00:00:00Z",
            "url": "https://github.com/ci4me/ai-erp-foundation/discussions/1",
            "comments": [],
        }
    ],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the login-feature dry-run fixture.")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output path (default: {DEFAULT_OUT}).")
    args = parser.parse_args(argv)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(LOGIN_FIXTURE, fh, indent=2)

    print(f"Wrote login fixture to {args.out}")
    print("  repo: ci4me/ai-erp-foundation (default branch: main)")
    print("  discussions: 1 (TEAM-REQUEST), issues: 0, prs: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
