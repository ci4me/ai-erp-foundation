#!/usr/bin/env python3
"""Executes a plan step by step against GitHub, with structured logging.

Three properties matter here:

1. **No shell injection.** Every external command is run as an argument *list*
   (``subprocess.run([...])``) — bodies, titles, and reasoning text are passed
   as single argv elements and are never interpolated into a shell string.
2. **Dry-run by default.** When ``apply`` is False every step is *recorded* with
   the exact command that would run, but nothing mutates GitHub. Pass
   ``apply=True`` (CLI ``--apply`` / ``PLANNER_APPLY=1``) to execute for real.
3. **Structured logging.** Every step is written to a JSON file via
   :mod:`simulation.tools.debug_logger`; the console only shows one summary line
   per step. There are no ad-hoc ``print`` debug statements.

``create_pr`` steps may target PR number ``"auto"`` in later chained steps
(review/merge); the executor remembers the PR it just created and substitutes
it. ``merge_pr`` deliberately uses a plain ``--merge`` (never ``--admin``) so a
human still owns any protected-branch override.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Optional

from simulation.tools.debug_logger import get_logger

DEFAULT_REPO = "ci4me/ai-erp-foundation"

# Remembers PRs created during a single execute_plan run so chained
# review/merge steps targeting "auto" can resolve to a concrete number.
_pr_number_mapping: dict[str, str] = {}


def _run_capture(
    cmd: list[str], *, apply: bool, cwd: str | None = None
) -> tuple[str, bool, Optional[str]]:
    """Run a command, returning ``(stdout, success, error)``.

    In dry-run (``apply`` False) the command is *not* executed; the caller is
    expected to log the intended command. The returned tuple is
    ``("", True, None)`` so dry-run steps record as successful no-ops.
    """
    if not apply:
        return "", True, None
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    ok = result.returncode == 0
    error = None if ok else (result.stderr.strip() or f"exit code {result.returncode}")
    return result.stdout, ok, error


def _command_for(action: str, number: Any, body: str, repo: str) -> Optional[list[str]]:
    """Map a (non-create) action to its ``gh`` argv list, or None if unknown."""
    if action == "close_pr":
        return ["gh", "pr", "close", str(number), "--comment", body, "--repo", repo]
    if action == "comment_issue":
        return ["gh", "issue", "comment", str(number), "--body", body, "--repo", repo]
    if action == "comment_discussion":
        # `gh api` targets the repo via the path, so no --repo flag.
        return [
            "gh", "api", f"/repos/{repo}/discussions/{number}/comments",
            "-f", f"body={body}",
        ]
    if action == "review_pr":
        return ["gh", "pr", "review", str(number), "--comment", "--body", body, "--repo", repo]
    if action == "merge_pr":
        return ["gh", "pr", "merge", str(number), "--merge", "--repo", repo]
    if action == "close_issue":
        return ["gh", "issue", "close", str(number), "--comment", body, "--repo", repo]
    return None


def execute_step(step: dict[str, Any], *, apply: bool, repo: str = DEFAULT_REPO) -> None:
    """Execute (or, in dry-run, record) a single plan step."""
    logger = get_logger()
    persona = step["persona"]
    action = step["action"]
    target = dict(step["target"])  # copy: we may rewrite "auto"
    body = step.get("body", "")
    files = step.get("files", {})

    # Resolve a chained "auto" PR target to the PR we just created.
    if target.get("number") == "auto":
        resolved = _pr_number_mapping.get("last_pr")
        if not resolved:
            logger.log(
                persona=persona, action=action, target=target, prompt_body=body,
                response_body=None, gh_command=None, gh_output=None,
                success=False, error="unresolved 'auto' PR target", dry_run=not apply,
            )
            return
        target["number"] = resolved

    number = target.get("number")

    if action == "create_pr":
        _create_pr(persona, number, body, files, apply=apply, repo=repo)
        return

    cmd = _command_for(action, number, body, repo)
    if cmd is None:
        logger.log(
            persona=persona, action=action, target=target, prompt_body=body,
            response_body=None, gh_command=None, gh_output=None,
            success=False, error=f"unknown action: {action}", dry_run=not apply,
        )
        return

    output, ok, error = _run_capture(cmd, apply=apply)

    # Self-authored PRs reject `pr review`; fall back to a plain comment.
    if action == "review_pr" and apply and output:
        lowered = output.lower()
        if "can not" in lowered or "cannot review" in lowered:
            cmd = ["gh", "pr", "comment", str(number), "--body", body, "--repo", repo]
            output, ok, error = _run_capture(cmd, apply=apply)

    logger.log(
        persona=persona, action=action, target=target, prompt_body=body,
        response_body=None, gh_command=" ".join(cmd), gh_output=output,
        success=ok, error=error, dry_run=not apply,
    )


def _create_pr(
    persona: str,
    issue_number: Any,
    body: str,
    files: dict[str, str],
    *,
    apply: bool,
    repo: str = DEFAULT_REPO,
) -> None:
    """Create a branch, write files, push, and open a PR for ``issue_number``."""
    logger = get_logger()
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    branch = f"auto-issue-{issue_number}-{stamp}"
    target = {"type": "issue", "number": issue_number}
    create_cmd = [
        "gh", "pr", "create",
        "--title", f"Auto PR for issue #{issue_number}",
        "--body", body,
        "--base", "main",
        "--head", branch,
        "--repo", repo,
    ]

    if not apply:
        logger.log(
            persona=persona, action="create_pr", target=target, prompt_body=body,
            response_body=None, gh_command=" ".join(create_cmd), gh_output=None,
            success=True, error=None, dry_run=True, files=list(files), branch=branch,
        )
        return

    for git_cmd in (
        ["git", "fetch", "origin", "main"],
        ["git", "checkout", "-b", branch, "origin/main"],
    ):
        _run_capture(git_cmd, apply=apply)
    for path, content in files.items():
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    _run_capture(["git", "add", *files.keys()], apply=apply)
    _run_capture(["git", "commit", "-m", f"Auto: implement issue #{issue_number}"], apply=apply)
    _run_capture(["git", "push", "origin", branch], apply=apply)

    output, ok, error = _run_capture(create_cmd, apply=apply)
    pr_url = output.strip()
    if pr_url:
        _pr_number_mapping["last_pr"] = pr_url.rstrip("/").split("/")[-1]
    logger.log(
        persona=persona, action="create_pr", target=target, prompt_body=body,
        response_body=None, gh_command=" ".join(create_cmd), gh_output=pr_url,
        success=ok and bool(pr_url), error=error, dry_run=False,
        files=list(files), branch=branch,
    )


def execute_plan(plan: dict[str, Any], *, apply: bool, repo: str = DEFAULT_REPO) -> None:
    """Execute every step in a plan sequentially, logging each one.

    Args:
        plan: the dict returned by
            :func:`simulation.tools.plan_builder.build_plan`.
        apply: when False (default behavior of the CLI) nothing mutates GitHub.
        repo: target ``owner/name``.
    """
    logger = get_logger()
    logger.set_mode(plan.get("mode"))
    mode_label = "APPLY" if apply else "DRY-RUN"
    print(
        f"── Executing {plan['total_steps']} step(s) [{mode_label}] "
        f"| run_id={logger.current_run_id}"
    )
    for step in plan["steps"]:
        execute_step(step, apply=apply, repo=repo)
        if apply:
            time.sleep(1)  # be gentle with secondary rate limits
    tail = "✅ Plan execution completed." if apply else "✅ Dry-run completed (no mutations)."
    print(f"{tail} Logs: logs/<date>/{logger.current_run_id}-step-*.json")
