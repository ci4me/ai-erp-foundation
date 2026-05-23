"""Architecture snapshot + diff tool.

Captures the framework's full GitHub state at a moment in time and
optionally diffs two snapshots to show what changed.

Snapshot contents
-----------------

- Open PRs (number, title, base/head, review decision, mergeable state,
  labels, author).
- Open issues (number, title, labels, milestone, assignees).
- Discussions (number, title, category, comment count).
- Milestones (with progress percentage).
- Labels (full list).
- Persona files (count, names — read from `.github/agent-prompts/`).
- Simulation scenarios (count, names — read from `simulation/scenarios/`).
- Scorecards (count, names — read from `simulation/scorecards/`).
- Workflow files (count, names — read from `.github/workflows/`).

Diff output
-----------

Markdown summary of added/removed/modified items between two snapshots.
Useful for weekly framework-velocity reports.

Usage
-----

::

    python -m simulation.tools.arch_snapshot --output snapshot-$(date +%Y%m%d).json
    python -m simulation.tools.arch_snapshot --diff prev.json curr.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[2]


def _gh(args: list[str], repo: str, *, jq: str | None = None) -> str:
    cmd = ["gh", *args, "-R", repo]
    if jq:
        cmd += ["--jq", jq]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout


def _gh_graphql(query: str, **vars: Any) -> dict[str, Any]:
    args = ["api", "graphql"]
    for k, v in vars.items():
        args += ["-F", f"{k}={v}"]
    args += ["-f", f"query={query}"]
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def snapshot(repo: str) -> dict[str, Any]:
    """Build the full snapshot dict."""
    snap: dict[str, Any] = {
        "repo": repo,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    prs_raw = _gh(
        ["pr", "list", "--state", "open", "--json",
         "number,title,baseRefName,headRefName,reviewDecision,labels,author,createdAt"],
        repo,
    )
    snap["open_prs"] = json.loads(prs_raw) if prs_raw.strip() else []

    issues_raw = _gh(
        ["issue", "list", "--state", "open", "--limit", "100",
         "--json", "number,title,labels,milestone,assignees,createdAt"],
        repo,
    )
    snap["open_issues"] = json.loads(issues_raw) if issues_raw.strip() else []

    discussions = _gh_graphql(
        "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { discussions(first: 50) { nodes { number title category { name } comments { totalCount } } } } }",
        owner=repo.split("/")[0], name=repo.split("/")[1],
    )
    snap["discussions"] = (
        discussions.get("data", {}).get("repository", {}).get("discussions", {}).get("nodes", [])
    )

    milestones_raw = _gh(["api", f"repos/{repo}/milestones?state=open"], repo)
    try:
        milestones = json.loads(milestones_raw) if milestones_raw.strip() else []
        snap["milestones"] = [
            {
                "number": m["number"],
                "title": m["title"],
                "open_issues": m["open_issues"],
                "closed_issues": m["closed_issues"],
            }
            for m in milestones
        ]
    except json.JSONDecodeError:
        snap["milestones"] = []

    labels_raw = _gh(["label", "list", "--limit", "100", "--json", "name,color"], repo)
    snap["labels"] = json.loads(labels_raw) if labels_raw.strip() else []

    snap["personas"] = _list_contents(repo, ".github/agent-prompts", suffix=".md", strip_prefix="_")
    snap["scenarios"] = _list_contents(repo, "simulation/scenarios", suffix=".yml", strip_prefix="_")
    snap["scorecards"] = _list_contents(repo, "simulation/scorecards", suffix=".json")
    snap["workflows"] = _list_contents(repo, ".github/workflows", suffix=".yml")

    return snap


def _list_contents(repo: str, path: str, *, suffix: str = "", strip_prefix: str = "") -> list[str]:
    raw = _gh(["api", f"repos/{repo}/contents/{path}"], repo)
    if not raw.strip():
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        return []
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        if suffix and not name.endswith(suffix):
            continue
        if strip_prefix and name.startswith(strip_prefix):
            continue
        names.append(name)
    return sorted(names)


def diff_snapshots(prev: dict[str, Any], curr: dict[str, Any]) -> str:
    """Render a Markdown diff of two snapshots."""
    lines: list[str] = [
        f"# Architecture diff — `{prev.get('repo')}`",
        "",
        f"**Previous:** {prev.get('captured_at')}",
        f"**Current:**  {curr.get('captured_at')}",
        "",
    ]

    for key, label in [
        ("open_prs", "Open PRs (by number)"),
        ("open_issues", "Open issues (by number)"),
        ("discussions", "Discussions (by number)"),
    ]:
        prev_ids = {item["number"] for item in prev.get(key, [])}
        curr_ids = {item["number"] for item in curr.get(key, [])}
        added = sorted(curr_ids - prev_ids)
        removed = sorted(prev_ids - curr_ids)
        if added or removed:
            lines += [f"## {label}", ""]
            if added:
                lines.append("**Added:** " + ", ".join(f"#{n}" for n in added))
            if removed:
                lines.append("**Closed:** " + ", ".join(f"#{n}" for n in removed))
            lines.append("")

    for key, label in [
        ("personas", "Personas in `.github/agent-prompts/`"),
        ("scenarios", "Scenarios in `simulation/scenarios/`"),
        ("scorecards", "Scorecards in `simulation/scorecards/`"),
        ("workflows", "Workflows in `.github/workflows/`"),
        ("labels", "Labels"),
    ]:
        prev_set = set(_names(prev.get(key, [])))
        curr_set = set(_names(curr.get(key, [])))
        added = sorted(curr_set - prev_set)
        removed = sorted(prev_set - curr_set)
        if added or removed:
            lines += [f"## {label}", ""]
            if added:
                lines.append("**Added:** " + ", ".join(f"`{n}`" for n in added))
            if removed:
                lines.append("**Removed:** " + ", ".join(f"`{n}`" for n in removed))
            lines.append("")

    if len(lines) <= 6:
        lines.append("_No changes between snapshots._")
    return "\n".join(lines) + "\n"


def _names(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item.get("name", "<noname>"))
        else:
            out.append(str(item))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="ci4me/ai-erp-foundation")
    parser.add_argument("--output", type=Path, default=None,
                        help="Write snapshot JSON to this path (default: stdout).")
    parser.add_argument("--diff", nargs=2, type=Path, default=None, metavar=("PREV", "CURR"),
                        help="Render a Markdown diff between two snapshot JSON files instead of capturing.")
    args = parser.parse_args()

    if args.diff:
        prev = json.loads(args.diff[0].read_text())
        curr = json.loads(args.diff[1].read_text())
        print(diff_snapshots(prev, curr))
        return 0

    if not shutil.which("gh"):
        print("ERROR: gh CLI not found in PATH.", file=sys.stderr)
        return 2

    snap = snapshot(args.repo)
    payload = json.dumps(snap, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.write_text(payload)
        print(f"wrote snapshot ({len(snap['open_prs'])} PRs, "
              f"{len(snap['open_issues'])} issues, "
              f"{len(snap['personas'])} personas) to {args.output}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
