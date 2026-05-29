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

# Markers a persona can place in an issue/PR body to pull other personas in.
REQUEST_MARKERS: tuple[str, ...] = (
    "REQUEST-REPLY-FROM:",
    "REQUEST-REVIEW-FROM:",
    "REQUEST-APPROVAL-FROM:",
    "QUESTION-TO:",
)

# Collaboration markers (debate / clarification / escalation / decisions). Their
# presence in a body is the cheap signal that an item's comments are worth
# fetching for the collaboration detectors in state_analyzer.
COLLABORATION_MARKERS: tuple[str, ...] = (
    "REQUEST-INFO:",
    "RESPONSE:",
    "ARGUMENT:",
    "COUNTER-PROPOSAL:",
    "REBUTTAL:",
    "EVIDENCE:",
    "RESOLUTION:",
    "OBJECTION:",
    "ESCALATION:",
    "EXPLANATION:",
    "DECISION-FROM-LEAD:",
)


def has_request_marker(text: str | None) -> bool:
    """True iff ``text`` contains any persona-request marker."""
    text = text or ""
    return any(marker in text for marker in REQUEST_MARKERS)


def has_collaboration_marker(text: str | None) -> bool:
    """True iff ``text`` contains any collaboration marker."""
    text = text or ""
    return any(marker in text for marker in COLLABORATION_MARKERS)


def run_gh(
    args: list[str], repo: str = DEFAULT_REPO, *, check: bool = True, repo_flag: bool = True
) -> str:
    """Run a ``gh`` command and return stdout.

    Args:
        args: argv for ``gh`` *without* the leading ``gh`` (e.g.
            ``["pr", "list", "--state", "open"]``).
        repo: ``owner/name`` appended as ``--repo`` when ``repo_flag`` is True.
        check: when True (default) a non-zero exit raises ``RuntimeError``;
            when False the stderr is swallowed and ``""`` is returned.
        repo_flag: append ``--repo``. Set False for ``gh api`` calls, which do
            not accept that flag (the repo lives in the request path instead).

    Returns:
        The command's stdout (possibly empty).
    """
    cmd = ["gh", *args] + (["--repo", repo] if repo_flag else [])
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


def fetch_comments(kind: str, number: Any, repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch the comments on an issue or PR (best-effort, [] on failure).

    Args:
        kind: ``"issue"`` or ``"pr"``.
        number: the issue/PR number.
    """
    raw = run_gh(
        [kind, "view", str(number), "--json", "comments", "--jq", ".comments"],
        repo,
        check=False,
    )
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def fetch_prs(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch open PRs, each annotated with ``reviews`` and ``has_code``."""
    raw = run_gh(
        [
            "pr", "list", "--state", "open",
            "--json", "number,title,body,headRefName,createdAt,updatedAt,labels,url,files",
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
        # PRs are few, and review-deadlock detection (OBJECTION markers) lives in
        # PR comments, so always fetch them.
        pr["comments"] = fetch_comments("pr", pr["number"], repo)
    return prs


def fetch_issues(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch open issues with labels, body, and (for request issues) comments."""
    raw = run_gh(
        [
            "issue", "list", "--state", "open",
            "--json", "number,title,body,labels,createdAt,updatedAt,url",
        ],
        repo,
    )
    issues: list[dict[str, Any]] = json.loads(raw) if raw.strip() else []
    for issue in issues:
        # Issues are numerous, so only pay for comments when the item is worth
        # inspecting: it already signals a request/collaboration thread, OR it is
        # a lifecycle item (an `epic` or any `phase/*`-labelled issue). Epic
        # lifecycle markers (DECOMPOSITION-PLAN, CONSENSUS-REACHED, SUB-TASK,
        # PHASE-CHANGE, ...) live in *comments* but are not request/collaboration
        # markers, so without this an epic's plan/consensus is invisible to the
        # planner and the epic can never advance past EPIC_UNDECOMPOSED.
        body = issue.get("body")
        label_names = {
            (lbl.get("name", "") if isinstance(lbl, dict) else str(lbl))
            for lbl in (issue.get("labels") or [])
        }
        is_lifecycle = "epic" in label_names or any(
            name.startswith("phase/") for name in label_names
        )
        issue["comments"] = (
            fetch_comments("issue", issue["number"], repo)
            if has_request_marker(body) or has_collaboration_marker(body) or is_lifecycle
            else []
        )
    return issues


def _normalize_discussion(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a REST discussion object to the analyzer's camelCase field names."""
    return {
        "number": raw.get("number"),
        "title": raw.get("title"),
        "body": raw.get("body"),
        "createdAt": raw.get("created_at") or raw.get("createdAt"),
        "updatedAt": raw.get("updated_at") or raw.get("updatedAt"),
        "url": raw.get("html_url") or raw.get("url"),
    }


def fetch_discussion_comments(number: Any, repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch a discussion's comments via REST (best-effort, [] on failure).

    Normalizes to ``{"body", "author": {"login"}}`` so collaboration detectors
    can read comments uniformly across issues, PRs, and discussions.
    """
    raw = run_gh(
        ["api", f"/repos/{repo}/discussions/{number}/comments"],
        repo,
        check=False,
        repo_flag=False,
    )
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [
        {
            "body": c.get("body", ""),
            "author": {"login": (c.get("user") or {}).get("login", "")},
            "createdAt": c.get("created_at") or c.get("createdAt"),
            "updatedAt": c.get("updated_at") or c.get("updatedAt"),
        }
        for c in data
    ]


def fetch_discussions(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    """Fetch open discussions, preferring the REST endpoint, GraphQL as fallback.

    Each discussion is annotated with its ``comments`` so the debate detector can
    inspect the thread. Repos/tokens without the Discussions feature yield an
    empty list rather than an error, so the planner keeps running on its
    PR/issue findings.
    """
    rest = run_gh(["api", f"/repos/{repo}/discussions"], repo, check=False, repo_flag=False)
    if rest.strip():
        try:
            data = json.loads(rest)
            if isinstance(data, list):
                discussions = [_normalize_discussion(d) for d in data]
                for disc in discussions:
                    disc["comments"] = fetch_discussion_comments(disc["number"], repo)
                return discussions
        except json.JSONDecodeError:
            pass

    # Fallback: GraphQL (some token scopes expose discussions only here).
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
        repo_flag=False,
    )
    if not raw.strip():
        return []
    try:
        nodes = json.loads(raw)
        return nodes if isinstance(nodes, list) else []
    except json.JSONDecodeError:
        return []


def fetch_all_state(repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Return the complete state snapshot consumed by the analyzer."""
    return {
        "prs": fetch_prs(repo),
        "issues": fetch_issues(repo),
        "discussions": fetch_discussions(repo),
    }
