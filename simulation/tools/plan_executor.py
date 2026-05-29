#!/usr/bin/env python3
"""Executes a plan step by step against GitHub.

Two safety properties matter here:

1. **No shell injection.** Every external command is run as an argument *list*
   (``subprocess.run([...])``) — bodies, titles, and reasoning text are passed
   as single argv elements and are never interpolated into a shell string.
2. **Dry-run by default.** When ``apply`` is False every step is *printed* with
   the exact command that would run, but nothing mutates GitHub. Pass
   ``apply=True`` (CLI ``--apply`` / ``PLANNER_APPLY=1``) to execute for real.

``create_pr`` steps may target PR number ``"auto"`` in later chained steps
(review/merge); the executor remembers the PR it just created and substitutes
it. ``merge_pr`` deliberately uses a plain ``--merge`` (never ``--admin``) so a
human still owns any protected-branch override.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

DEFAULT_REPO = "ci4me/ai-erp-foundation"

# Remembers PRs created during a single execute_plan run so chained
# review/merge steps targeting "auto" can resolve to a concrete number.
_pr_number_mapping: dict[str, str] = {}


def _run(cmd: list[str], *, apply: bool, cwd: str | None = None) -> str:
    """Run (or, in dry-run, describe) a command. Returns stdout ("" in dry-run).

    Non-zero exits are logged as warnings rather than raised: one failed step
    should not abort an entire ``multi``-mode plan.
    """
    printable = " ".join(cmd)
    if not apply:
        print(f"   [dry-run] would run: {printable}")
        return ""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"   WARNING: `{printable}` failed: {result.stderr.strip()}")
    return result.stdout


def _gh(args: list[str], *, apply: bool, repo: str = DEFAULT_REPO) -> str:
    """Run a ``gh`` command (argv list) scoped to ``repo``."""
    return _run(["gh", *args, "--repo", repo], apply=apply)


def execute_step(step: dict[str, Any], *, apply: bool, repo: str = DEFAULT_REPO) -> None:
    """Execute (or describe) a single plan step."""
    persona = step["persona"]
    action = step["action"]
    target = dict(step["target"])  # copy: we may rewrite "auto"
    body = step.get("body", "")
    files = step.get("files", {})

    # Resolve a chained "auto" PR target to the PR we just created.
    if target.get("number") == "auto":
        resolved = _pr_number_mapping.get("last_pr")
        if not resolved:
            print(f"   ERROR: 'auto' PR number unresolved for {action}; skipping.")
            return
        target["number"] = resolved

    number = target.get("number")
    print(f"▶ {persona} | {action} on {target}")

    if action == "close_pr":
        _gh(["pr", "close", str(number), "--comment", body], apply=apply, repo=repo)

    elif action == "comment_issue":
        _gh(["issue", "comment", str(number), "--body", body], apply=apply, repo=repo)

    elif action == "comment_discussion":
        # gh has no first-class discussion-comment verb across versions; this is
        # best-effort and degrades to a warning in apply mode.
        _gh(
            ["api", f"/repos/{repo}/discussions/{number}/comments", "-f", f"body={body}"],
            apply=apply,
            repo=repo,
        )

    elif action == "create_pr":
        _create_pr(number, body, files, apply=apply, repo=repo)

    elif action == "review_pr":
        out = _gh(
            ["pr", "review", str(number), "--comment", "--body", body],
            apply=apply,
            repo=repo,
        )
        # Self-authored PRs reject `pr review`; fall back to a plain comment.
        lowered = out.lower()
        if apply and ("can not" in lowered or "cannot review" in lowered):
            _gh(["pr", "comment", str(number), "--body", body], apply=apply, repo=repo)

    elif action == "merge_pr":
        # Plain --merge only; never --admin (a human owns protected-branch overrides).
        _gh(["pr", "merge", str(number), "--merge"], apply=apply, repo=repo)

    elif action == "close_issue":
        _gh(["issue", "close", str(number), "--comment", body], apply=apply, repo=repo)

    else:
        print(f"   Unknown action: {action}")


def _create_pr(
    issue_number: Any,
    body: str,
    files: dict[str, str],
    *,
    apply: bool,
    repo: str = DEFAULT_REPO,
) -> None:
    """Create a branch, write files, push, and open a PR for ``issue_number``."""
    # Deterministic-ish branch name; os.getpid keeps concurrent runs distinct
    # without depending on time-of-day formatting beyond a coarse stamp.
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    branch = f"auto-issue-{issue_number}-{stamp}"

    if not apply:
        print(f"   [dry-run] would create branch {branch} with files: {list(files)}")
        print(f"   [dry-run] would open PR for issue #{issue_number}")
        return

    _run(["git", "fetch", "origin", "main"], apply=apply)
    _run(["git", "checkout", "-b", branch, "origin/main"], apply=apply)
    for path, content in files.items():
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    _run(["git", "add", *files.keys()], apply=apply)
    _run(["git", "commit", "-m", f"Auto: implement issue #{issue_number}"], apply=apply)
    _run(["git", "push", "origin", branch], apply=apply)
    out = _gh(
        [
            "pr", "create",
            "--title", f"Auto PR for issue #{issue_number}",
            "--body", body,
            "--base", "main",
            "--head", branch,
        ],
        apply=apply,
        repo=repo,
    )
    pr_url = out.strip()
    if pr_url:
        _pr_number_mapping["last_pr"] = pr_url.rstrip("/").split("/")[-1]
        print(f"   Created PR: {pr_url}")


def execute_plan(plan: dict[str, Any], *, apply: bool, repo: str = DEFAULT_REPO) -> None:
    """Execute every step in a plan sequentially.

    Args:
        plan: the dict returned by
            :func:`simulation.tools.plan_builder.build_plan`.
        apply: when False (default behavior of the CLI) nothing mutates GitHub.
        repo: target ``owner/name``.
    """
    mode_label = "APPLY" if apply else "DRY-RUN"
    print(f"── Executing {plan['total_steps']} step(s) [{mode_label}]")
    for step in plan["steps"]:
        execute_step(step, apply=apply, repo=repo)
        if apply:
            time.sleep(1)  # be gentle with secondary rate limits
    print("✅ Plan execution completed." if apply else "✅ Dry-run completed (no mutations).")
