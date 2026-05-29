#!/usr/bin/env python3
"""Enforce branch protection on the default branch via the GitHub API.

SAFETY: dry-run by default. This script mutates SHARED repository settings, so
it prints the request it *would* send and exits unless ``--apply`` is passed.
Requires an authenticated ``gh`` CLI with admin rights on the repo.

Usage:
    python3 scripts/enforce_branch_protection.py                 # dry-run (safe)
    python3 scripts/enforce_branch_protection.py --apply         # actually apply
    python3 scripts/enforce_branch_protection.py --repo o/r --branch main --apply
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

DEFAULT_REPO = "ci4me/ai-erp-foundation"
DEFAULT_BRANCH = "main"

# Minimal, reasonable protection: require 1 approving review; admins not exempt
# from the configured rules beyond what GitHub allows. enforce_admins=False keeps
# automation (and humans) able to administer the repo.
PROTECTION_PAYLOAD = {
    "required_status_checks": None,
    "enforce_admins": False,
    "required_pull_request_reviews": {"required_approving_review_count": 1},
    "restrictions": None,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce branch protection.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--apply", action="store_true", help="Actually apply (mutates shared settings).")
    args = parser.parse_args(argv)

    endpoint = f"/repos/{args.repo}/branches/{args.branch}/protection"
    payload = json.dumps(PROTECTION_PAYLOAD)

    if not args.apply:
        print("[dry-run] would PUT branch protection (pass --apply to execute):")
        print(f"  endpoint: {endpoint}")
        print(f"  payload:  {payload}")
        return 0

    print(f"Applying branch protection to {args.repo}@{args.branch} ...")
    result = subprocess.run(
        ["gh", "api", "--method", "PUT", endpoint, "--input", "-"],
        input=payload,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Failed to set branch protection:\n{result.stderr.strip()}", file=sys.stderr)
        return 1
    print("Branch protection updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
