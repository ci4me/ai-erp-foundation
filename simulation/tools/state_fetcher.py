#!/usr/bin/env python3
"""Fetches the current GitHub state via the ``gh`` CLI.

Produces a single structured snapshot — open PRs (with their changed files and
reviews), open issues, and open discussions — that the analyzer consumes.

All ``gh`` invocations go through :func:`run_gh`, which uses an argument *list*
(never ``shell=True``) so repository names, numbers, and JSON field lists can
never be interpreted by a shell. PR/issue fetches raise on failure (the planner
cannot reason about a half-known state); discussion fetches degrade to an empty
list because not every repo/token has the Discussions feature enabled.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

DEFAULT_REPO = "ci4me/ai-erp-foundation"

# Extensions that make a PR a "real" code change rather than notes/docs.
CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".php", ".js", ".py", ".go", ".java", ".rb", ".ts", ".jsx", ".tsx",
        ".c", ".cpp", ".cc", ".h", ".hpp", ".rs", ".sql", ".kt", ".swift",
        ".cs", ".vb", ".scala",
    }
)


def run_gh(args: list[str], repo: str = DEFAULT_REPO, *, check: bool = True) -> str:
    """Run ``gh <args> --repo <repo>`` and return stdout.

    Args:
        args: argv for ``gh`` *without* the leading ``gh`` (e.g.
            ``["pr", "list", "--state", "open"]``).
        repo: ``owner/name`` appended as ``--repo``.
        check: when True (default) a non-zero exit raises ``RuntimeError``;
            when False the stderr is swallowed and ``""`` is returned.

    Returns:
        The command's stdout (possibly empty).
    """
    cmd = ["gh", *args, "--repo", repo]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if check:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
            )
        return ""
    return result.stdout


def _has_code(pr: dict[str, Any]) -> bool:
    """True iff any changed file in the PR carries a source-code extension."""
    for f in pr.get("files", []) or []:
        path = f.get("path", "")
        if any(path.endswith(ext) for ext in CODE_EXTENSIONS):
            return True
    return False


def fetch_prs(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch open PRs, each annotated with ``reviews`` and ``has_code``."""
    raw = run_gh(
        [
            "pr", "list", "--state", "open",
            "--json", "number,title,headRefName,createdAt,updatedAt,labels,url,files",
        ],
        repo,
    )
    prs: list[dict[str, Any]] = json.loads(raw) if raw.strip() else []
    for pr in prs:
        reviews_raw = run_gh(
            ["pr", "view", str(pr["number"]), "--json", "reviews", "--jq", ".reviews"],
            repo,
            check=False,
        )
        try:
            pr["reviews"] = json.loads(reviews_raw) if reviews_raw.strip() else []
        except json.JSONDecodeError:
            pr["reviews"] = []
        pr["has_code"] = _has_code(pr)
    return prs


def fetch_issues(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch open issues with labels and body."""
    raw = run_gh(
        [
            "issue", "list", "--state", "open",
            "--json", "number,title,body,labels,createdAt,updatedAt,url",
        ],
        repo,
    )
    return json.loads(raw) if raw.strip() else []


def fetch_discussions(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch open discussions via the GraphQL API.

    Discussions are a GraphQL-only feature; repos without it (or tokens lacking
    the scope) yield an empty list rather than an error, so the planner keeps
    running on its PR/issue findings.
    """
    owner, _, name = repo.partition("/")
    query = (
        "query($owner:String!,$name:String!){repository(owner:$owner,name:$name)"
        "{discussions(first:50,states:OPEN){nodes{number title body createdAt updatedAt url}}}}"
    )
    raw = run_gh(
        [
            "api", "graphql",
            "-f", f"query={query}",
            "-F", f"owner={owner}",
            "-F", f"name={name}",
            "--jq", ".data.repository.discussions.nodes",
        ],
        repo,
        check=False,
    )
    if not raw.strip():
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def fetch_all_state(repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Return the complete state snapshot consumed by the analyzer."""
    return {
        "prs": fetch_prs(repo),
        "issues": fetch_issues(repo),
        "discussions": fetch_discussions(repo),
    }
