"""Run `next_prompt.py` against a captured GitHub-state fixture.

This is the sandbox bridge used when an environment can run Python but cannot
run an authenticated `gh` CLI. Capture live state with whatever tool is
available, write it as JSON, then replay the production scheduler without
modifying `next_prompt.py` itself.

Fixture shape
-------------

The minimal fixture is::

    {
      "pr": {"number": 35, "title": "...", "comments": [], "reviews": [], "files": []},
      "issues": [],
      "discussions": [],
      "milestones": [],
      "diff": "diff --git ..."
    }

`pr` may also be `prs` when multiple open PRs are needed. The runner implements
only read-only `gh` calls used by `next_prompt.py`; it refuses mutation calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from simulation.tools import next_prompt, next_prompt_legacy


def _strip_repo_flags(args: list[str]) -> list[str]:
    """Remove `-R owner/repo` pairs so fixture matching is simpler."""
    clean: list[str] = []
    index = 0
    while index < len(args):
        if args[index] == "-R" and index + 1 < len(args):
            index += 2
            continue
        clean.append(args[index])
        index += 1
    return clean


def _open_prs(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(fixture.get("prs"), list):
        return fixture["prs"]
    if isinstance(fixture.get("pr"), dict):
        return [fixture["pr"]]
    return []


def build_fixture_gh(fixture: dict[str, Any]):
    """Return a fake `_gh(args, repo)` function backed by fixture data."""

    def fake_gh(args: list[str], repo: str) -> str:
        args = _strip_repo_flags(args)
        prs = _open_prs(fixture)
        issues = fixture.get("issues") or []
        discussions = fixture.get("discussions") or []
        milestones = fixture.get("milestones") or []

        if args[:2] == ["pr", "list"]:
            return json.dumps([
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "body": pr.get("body", ""),
                    "reviewDecision": pr.get("reviewDecision", ""),
                    "labels": pr.get("labels", []),
                    "author": pr.get("author", {}),
                    "headRefName": pr.get("headRefName", ""),
                    "baseRefName": pr.get("baseRefName", ""),
                    "url": pr.get("url", ""),
                }
                for pr in prs
            ])

        if len(args) >= 3 and args[:2] == ["pr", "view"]:
            number = int(args[2])
            pr = next((item for item in prs if int(item.get("number", -1)) == number), None)
            return json.dumps(pr or {})

        if len(args) >= 3 and args[:2] == ["pr", "diff"]:
            if isinstance(fixture.get("diffs"), dict):
                return str(fixture["diffs"].get(str(args[2]), ""))
            return str(fixture.get("diff", ""))

        if args[:2] == ["issue", "list"]:
            return json.dumps(issues)

        if len(args) >= 3 and args[:2] == ["issue", "view"]:
            number = int(args[2])
            issue = next((item for item in issues if int(item.get("number", -1)) == number), None)
            return json.dumps(issue or {"number": number, "title": "", "body": "", "labels": []})

        if args and args[0] == "api":
            if len(args) >= 2 and args[1] == "graphql":
                return json.dumps({"data": {"repository": {"discussions": {"nodes": discussions}}}})
            if len(args) >= 2 and "/milestones" in args[1]:
                return json.dumps(milestones)
            if len(args) >= 2 and "/contents/" in args[1]:
                return json.dumps([])

        raise RuntimeError("fixture does not implement gh call: " + " ".join(args))

    return fake_gh


def run_from_fixture(
    fixture_path: Path,
    *,
    repo: str,
    output: Path | None,
    probe_only: bool,
    max_diff_chars: int,
    post_mode: str,
) -> int:
    """Patch the gh shim, run the scheduler, and print/write output.

    ``gather_repo_state``/``resolve_priority``/``render_prompt`` were extracted
    into ``next_prompt_legacy``; they resolve ``_gh`` in *that* module's
    namespace, so the fixture shim must be installed there. We also bind it on
    the ``next_prompt`` facade so the public surface stays consistent.
    """
    fixture = json.loads(fixture_path.read_text())
    fake_gh = build_fixture_gh(fixture)
    next_prompt_legacy._gh = fake_gh  # type: ignore[assignment]
    next_prompt._gh = fake_gh  # type: ignore[method-assign]

    state = next_prompt.gather_repo_state(repo)
    priority, context = next_prompt.resolve_priority(state, repo)
    if probe_only:
        print(f"priority: {priority}")
        print(f"context: {json.dumps(next_prompt._context_for_probe(context), indent=2, default=str)}")
        print(f"open_prs: {len(state.open_prs)}")
        print(f"changes_requested: {len(state.prs_with_changes_requested)}")
        print(f"existing_personas: {sorted(state.existing_personas)}")
        print(f"existing_scenarios: {sorted(state.existing_scenarios)}")
        return 0

    prompt = next_prompt.render_prompt(
        repo,
        priority,
        context,
        state,
        max_diff_chars=max_diff_chars,
        post_mode=post_mode,
    )
    if output:
        output.write_text(prompt)
        print(f"wrote {len(prompt)} chars to {output}")
    else:
        print(prompt)
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run next_prompt.py from a read-only GitHub-state fixture.")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--repo", default="ci4me/ai-erp-foundation")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--max-diff-chars", type=int, default=24000)
    parser.add_argument("--post-mode", choices=["real", "dry-run"], default="dry-run")
    args = parser.parse_args()
    return run_from_fixture(
        args.fixture,
        repo=args.repo,
        output=args.output,
        probe_only=args.probe_only,
        max_diff_chars=args.max_diff_chars,
        post_mode=args.post_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
