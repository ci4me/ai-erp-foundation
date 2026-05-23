"""Generate the exact autonomous-loop prompt for the next iteration.

The loop has two responsibilities:

1. Read current GitHub state and decide the next action.
2. Render that action from repository-owned templates and persona prompts.

Prompt content lives in `.github/action-templates/*.md`.
Persona behavior lives in `.github/agent-prompts/*.md`.

Usage
-----

::

    python -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation
    python -m simulation.tools.next_prompt --output /tmp/next.md
    python -m simulation.tools.next_prompt --probe-only

Exit codes
----------

- ``0`` - prompt generated successfully.
- ``2`` - template data invalid, GitHub unavailable, or an unsupported fallback command.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - repo requirements include PyYAML.
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_PROMPTS_DIR = REPO_ROOT / ".github" / "agent-prompts"
ACTION_TEMPLATES_DIR = REPO_ROOT / ".github" / "action-templates"
ACTION_CATALOG_PATH = ACTION_TEMPLATES_DIR / "catalog.yml"
POLICIES_PATH = ACTION_TEMPLATES_DIR / "policies.yml"
PERSONA_ROSTER_PATH = AGENT_PROMPTS_DIR / "roster.yml"
SCENARIO_CATALOG_PATH = REPO_ROOT / "simulation" / "scenarios" / "catalog.yml"


@dataclass(frozen=True)
class MarkdownDoc:
    """Markdown file split into frontmatter and body."""

    path: Path
    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class RepoState:
    """Snapshot of GitHub and local repo state used for priority resolution."""

    open_prs: list[dict[str, Any]]
    open_issues: list[dict[str, Any]]
    open_discussions: list[dict[str, Any]]
    existing_personas: set[str]
    existing_scenarios: set[str]
    prs_with_changes_requested: list[dict[str, Any]]
    open_milestones: list[dict[str, Any]] = field(default_factory=list)


def _gh(args: list[str], repo: str) -> str:
    """Run `gh` when available, otherwise use a stdlib GitHub REST bridge.

    The autonomous loop is often executed from restricted sandboxes: ChatGPT,
    Codex, CI jobs, or local terminals that may not have `gh` installed. This
    adapter keeps the rest of the scheduler honest by preserving the tiny subset
    of `gh` command shapes that `next_prompt.py` uses, while falling back to
    public GitHub REST/GraphQL calls for read-only discovery.

    Write operations are intentionally not emulated here. Action templates render
    real `gh` mutation commands for the *agent* to run after validation; this
    function only reads state so the next action can be selected safely.
    """
    command = ["gh", *args]
    if args and args[0] != "api":
        command.extend(["-R", repo])

    if shutil.which("gh"):
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
        fallback = _gh_rest_fallback(args, repo)
        if fallback is not None:
            return fallback
        raise RuntimeError(f"gh failed: {' '.join(command)}\n{result.stderr.strip()}")

    fallback = _gh_rest_fallback(args, repo)
    if fallback is not None:
        return fallback
    raise RuntimeError(
        "gh CLI not found and Python REST fallback does not support: "
        f"{' '.join(args)}"
    )


def _github_api_json(
    repo: str,
    path: str,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    """Call GitHub REST/GraphQL with Python stdlib only.

    `repo` is accepted for logging and future host routing; `path` may be either
    a full `https://api.github.com/...` URL or an API-relative path such as
    `repos/owner/name/pulls`.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    url = path if path.startswith("https://") else f"https://api.github.com/{path.lstrip('/')}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", accept)
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "ai-erp-foundation-next-prompt")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network shaped
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network shaped
        raise RuntimeError(f"GitHub API failed for {url}: {exc.reason}") from exc

    return json.loads(raw) if raw.strip() else None


def _github_url_text(url: str, *, accept: str = "text/plain") -> str:
    """Fetch a text URL from GitHub using optional `GITHUB_TOKEN` auth."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    request = urllib.request.Request(url)
    request.add_header("Accept", accept)
    request.add_header("User-Agent", "ai-erp-foundation-next-prompt")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network shaped
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub text fetch {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network shaped
        raise RuntimeError(f"GitHub text fetch failed for {url}: {exc.reason}") from exc


def _gh_rest_fallback(args: list[str], repo: str) -> str | None:
    """Emulate the read-only `gh` commands used by this tool."""
    if not args:
        return None
    try:
        if args[:2] == ["pr", "list"]:
            return json.dumps(_rest_list_open_prs(repo))
        if args[:2] == ["issue", "list"]:
            return json.dumps(_rest_list_open_issues(repo))
        if args[:2] == ["pr", "view"] and len(args) >= 3:
            return json.dumps(_rest_pr_view(repo, int(args[2])))
        if args[:2] == ["pr", "diff"] and len(args) >= 3:
            return _github_url_text(f"https://github.com/{repo}/pull/{int(args[2])}.diff")
        if args[:2] == ["issue", "view"] and len(args) >= 3:
            return json.dumps(_rest_issue_view(repo, int(args[2])))
        if args and args[0] == "api" and len(args) >= 2:
            return _rest_api_command(repo, args[1:])
    except (ValueError, json.JSONDecodeError):
        return None
    return None


def _rest_api_command(repo: str, args: list[str]) -> str | None:
    """Support `gh api ...` calls used by the scheduler."""
    if not args:
        return None
    if args[0] == "graphql":
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            # Public REST can read most state, but GitHub Discussions GraphQL is
            # token-gated. Empty discussions are safer than failing the whole
            # loop in unauthenticated public-read mode.
            return json.dumps({"data": {"repository": {"discussions": {"nodes": []}}}})
        fields: dict[str, str] = {}
        index = 1
        while index < len(args):
            if args[index] == "-f" and index + 1 < len(args) and "=" in args[index + 1]:
                key, value = args[index + 1].split("=", 1)
                fields[key] = value
                index += 2
            else:
                index += 1
        query = fields.pop("query", "")
        data = _github_api_json(repo, "graphql", method="POST", data={"query": query, "variables": fields})
        return json.dumps(data)

    path = args[0]
    data = _github_api_json(repo, path)
    return json.dumps(data)


def _rest_list_open_prs(repo: str) -> list[dict[str, Any]]:
    """Return open PRs normalized to the `gh pr list --json ...` shape."""
    pulls = _github_api_json(repo, f"repos/{repo}/pulls?state=open&per_page=100") or []
    result: list[dict[str, Any]] = []
    for pull in pulls if isinstance(pulls, list) else []:
        number = int(pull.get("number"))
        issue = _rest_issue_view(repo, number)
        result.append({
            "number": number,
            "title": pull.get("title") or issue.get("title") or "",
            "body": pull.get("body") or issue.get("body") or "",
            "reviewDecision": _rest_review_decision(repo, number),
            "labels": issue.get("labels") or [],
            "author": _rest_author(pull.get("user")),
            "headRefName": (pull.get("head") or {}).get("ref") or "",
            "baseRefName": (pull.get("base") or {}).get("ref") or "",
            "url": pull.get("html_url") or f"https://github.com/{repo}/pull/{number}",
        })
    return result


def _rest_list_open_issues(repo: str) -> list[dict[str, Any]]:
    """Return open non-PR issues normalized to the `gh issue list` shape."""
    issues = _github_api_json(repo, f"repos/{repo}/issues?state=open&per_page=100") or []
    result: list[dict[str, Any]] = []
    for issue in issues if isinstance(issues, list) else []:
        if issue.get("pull_request"):
            continue
        result.append(_normalize_issue(issue))
    return result


def _rest_issue_view(repo: str, number: int) -> dict[str, Any]:
    """Return one issue normalized to the `gh issue view --json ...` shape."""
    issue = _github_api_json(repo, f"repos/{repo}/issues/{number}") or {}
    return _normalize_issue(issue)


def _rest_pr_view(repo: str, number: int) -> dict[str, Any]:
    """Return PR details normalized to the `gh pr view --json ...` shape."""
    pull = _github_api_json(repo, f"repos/{repo}/pulls/{number}") or {}
    issue = _rest_issue_view(repo, number)
    comments_raw = _github_api_json(repo, f"repos/{repo}/issues/{number}/comments?per_page=100") or []
    reviews_raw = _github_api_json(repo, f"repos/{repo}/pulls/{number}/reviews?per_page=100") or []
    files_raw = _github_api_json(repo, f"repos/{repo}/pulls/{number}/files?per_page=100") or []
    return {
        "number": number,
        "title": pull.get("title") or issue.get("title") or "",
        "body": pull.get("body") or issue.get("body") or "",
        "labels": issue.get("labels") or [],
        "author": _rest_author(pull.get("user") or issue.get("author")),
        "headRefName": (pull.get("head") or {}).get("ref") or "",
        "baseRefName": (pull.get("base") or {}).get("ref") or "",
        "comments": [_normalize_comment(item) for item in comments_raw if isinstance(item, dict)],
        "reviews": [_normalize_review(item) for item in reviews_raw if isinstance(item, dict)],
        "files": [_normalize_file(item) for item in files_raw if isinstance(item, dict)],
        "url": pull.get("html_url") or issue.get("url") or f"https://github.com/{repo}/pull/{number}",
        "reviewDecision": _rest_review_decision(repo, number),
    }


def _rest_review_decision(repo: str, number: int) -> str:
    """Approximate GraphQL `reviewDecision` from REST review states."""
    reviews = _github_api_json(repo, f"repos/{repo}/pulls/{number}/reviews?per_page=100") or []
    states: list[str] = []
    for review in reviews if isinstance(reviews, list) else []:
        state = str(review.get("state") or "").upper()
        if state in {"APPROVED", "CHANGES_REQUESTED"}:
            states.append(state)
    return states[-1] if states else ""


def _normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Normalize REST issue JSON into the subset used by the scheduler."""
    milestone = issue.get("milestone")
    return {
        "number": issue.get("number"),
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "labels": [_normalize_label(label) for label in issue.get("labels") or []],
        "milestone": _normalize_milestone(milestone) if isinstance(milestone, dict) else None,
        "url": issue.get("html_url") or issue.get("url") or "",
        "author": _rest_author(issue.get("user")),
    }


def _normalize_label(label: Any) -> dict[str, Any]:
    """Normalize a label string/object into a dict with `name`."""
    if isinstance(label, dict):
        return {"name": str(label.get("name") or "")}
    return {"name": str(label)}


def _normalize_milestone(milestone: dict[str, Any]) -> dict[str, Any]:
    """Normalize REST milestone JSON into the subset used by templates."""
    return {
        "number": milestone.get("number"),
        "title": milestone.get("title") or "",
        "description": milestone.get("description") or "",
        "state": milestone.get("state") or "",
        "open_issues": milestone.get("open_issues") or 0,
        "closed_issues": milestone.get("closed_issues") or 0,
        "due_on": milestone.get("due_on"),
        "url": milestone.get("html_url") or milestone.get("url") or "",
    }


def _normalize_comment(comment: dict[str, Any]) -> dict[str, Any]:
    """Normalize REST issue comment JSON into the `gh pr view` shape."""
    return {
        "body": comment.get("body") or "",
        "author": _rest_author(comment.get("user")),
        "createdAt": comment.get("created_at") or "",
        "url": comment.get("html_url") or comment.get("url") or "",
    }


def _normalize_review(review: dict[str, Any]) -> dict[str, Any]:
    """Normalize REST pull-request review JSON into the `gh pr view` shape."""
    return {
        "body": review.get("body") or "",
        "state": review.get("state") or "",
        "author": _rest_author(review.get("user")),
        "submittedAt": review.get("submitted_at") or "",
        "url": review.get("html_url") or review.get("url") or "",
    }


def _normalize_file(file_info: dict[str, Any]) -> dict[str, Any]:
    """Normalize REST changed-file JSON into the `gh pr view` shape."""
    filename = file_info.get("filename") or file_info.get("path") or ""
    return {
        "path": filename,
        "filename": filename,
        "status": file_info.get("status") or "",
        "additions": file_info.get("additions") or 0,
        "deletions": file_info.get("deletions") or 0,
        "changes": file_info.get("changes") or 0,
    }


def _rest_author(user: Any) -> dict[str, str]:
    """Normalize REST user JSON into a dict with `login`."""
    if isinstance(user, dict):
        return {"login": str(user.get("login") or "unknown")}
    return {"login": "unknown"}


def _parse_markdown_doc(path: Path) -> MarkdownDoc:
    text = path.read_text()
    if not text.startswith("---\n"):
        return MarkdownDoc(path=path, frontmatter={}, body=text.strip())

    parts = text.split("---\n", 2)
    if len(parts) != 3:
        return MarkdownDoc(path=path, frontmatter={}, body=text.strip())

    raw_frontmatter = parts[1]
    body = parts[2].strip()
    if yaml is None:
        frontmatter = _parse_tiny_yaml(raw_frontmatter)
    else:
        loaded = yaml.safe_load(raw_frontmatter) or {}
        frontmatter = loaded if isinstance(loaded, dict) else {}
    return MarkdownDoc(path=path, frontmatter=frontmatter, body=body)


def _parse_tiny_yaml(raw: str) -> dict[str, Any]:
    """Tiny fallback for the simple frontmatter shape used in this repo."""
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            parsed.setdefault(current_key, []).append(line[4:].split("#", 1)[0].strip().strip('"'))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.split("#", 1)[0].strip()
        if value == "":
            parsed[current_key] = []
        elif value.lower() == "true":
            parsed[current_key] = True
        elif value.lower() == "false":
            parsed[current_key] = False
        else:
            parsed[current_key] = value.strip('"')
    return parsed


def _load_persona_index() -> dict[str, MarkdownDoc]:
    personas: dict[str, MarkdownDoc] = {}
    if not AGENT_PROMPTS_DIR.exists():
        return personas

    for path in sorted(AGENT_PROMPTS_DIR.glob("*.md")):
        if path.name.startswith("_") or path.name == "README.md":
            continue
        doc = _parse_markdown_doc(path)
        persona_id = str(doc.frontmatter.get("id") or path.stem)
        personas[persona_id] = doc
    return personas


def _load_action_template(priority: str) -> MarkdownDoc:
    file_name = _template_name_for_action(priority)
    path = ACTION_TEMPLATES_DIR / file_name
    if not path.exists():
        raise RuntimeError(f"missing action template: {path.relative_to(REPO_ROOT)}")
    return _parse_markdown_doc(path)


def _template_name_for_action(action_id: str) -> str:
    for action in _load_action_catalog():
        if action.get("id") == action_id and action.get("template"):
            return str(action["template"])
    return action_id.replace("_", "-") + ".md"


def _load_action_catalog() -> list[dict[str, Any]]:
    if not ACTION_CATALOG_PATH.exists():
        return []
    if yaml is None:
        return []
    loaded = yaml.safe_load(ACTION_CATALOG_PATH.read_text()) or {}
    actions = loaded.get("actions") or []
    return actions if isinstance(actions, list) else []


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    return loaded if isinstance(loaded, dict) else {}


def _persona_catalog() -> list[str]:
    data = _load_yaml_file(PERSONA_ROSTER_PATH)
    personas = data.get("personas") or []
    if isinstance(personas, list):
        return [str(persona) for persona in personas]
    return sorted(_load_persona_index())


def _scenario_catalog() -> list[str]:
    data = _load_yaml_file(SCENARIO_CATALOG_PATH)
    scenarios = data.get("scenarios") or []
    if isinstance(scenarios, list):
        return [str(scenario) for scenario in scenarios]
    return sorted(_local_stems(REPO_ROOT / "simulation" / "scenarios", ".yml"))


def _operating_model_paths() -> list[str]:
    data = _load_yaml_file(POLICIES_PATH)
    return [str(path) for path in data.get("operating_model_paths", [])]


def _load_template_partial(file_name: str, fallback: str = "") -> str:
    path = ACTION_TEMPLATES_DIR / file_name
    if path.exists():
        return _parse_markdown_doc(path).body
    return fallback


def _local_stems(directory: Path, suffix: str) -> set[str]:
    if not directory.exists():
        return set()
    return {
        path.name.removesuffix(suffix)
        for path in directory.glob(f"*{suffix}")
        if not path.name.startswith("_") and path.name not in {"README.md", "catalog.yml"}
    }


def _remote_stems(repo: str, directory: str, suffix: str) -> set[str]:
    try:
        raw = _gh(["api", f"repos/{repo}/contents/{directory}"], repo)
        entries = json.loads(raw)
    except (RuntimeError, json.JSONDecodeError):
        return set()
    if not isinstance(entries, list):
        return set()
    return {
        entry["name"].removesuffix(suffix)
        for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("name", "")).endswith(suffix)
        and not str(entry.get("name", "")).startswith("_")
        and str(entry.get("name", "")) != "README.md"
    }


def gather_repo_state(repo: str) -> RepoState:
    """Query gh CLI plus local repo contents for priority inputs."""
    prs_json = _gh(
        [
            "pr",
            "list",
            "--state",
            "open",
            "--json",
            "number,title,body,reviewDecision,labels,author,headRefName,baseRefName",
        ],
        repo,
    )
    open_prs = json.loads(prs_json) if prs_json.strip() else []

    issues_json = _gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,body,labels,milestone",
        ],
        repo,
    )
    open_issues = json.loads(issues_json) if issues_json.strip() else []
    open_discussions = _fetch_discussions(repo)
    open_milestones = _fetch_milestones(repo)

    existing_personas = _local_stems(AGENT_PROMPTS_DIR, ".md")
    if not existing_personas:
        existing_personas = _remote_stems(repo, ".github/agent-prompts", ".md")

    existing_scenarios = _local_stems(REPO_ROOT / "simulation" / "scenarios", ".yml")
    if not existing_scenarios:
        existing_scenarios = _remote_stems(repo, "simulation/scenarios", ".yml")

    prs_with_changes_requested = [
        pr for pr in open_prs if pr.get("reviewDecision") == "CHANGES_REQUESTED"
    ]

    return RepoState(
        open_prs=open_prs,
        open_issues=open_issues,
        open_discussions=open_discussions,
        existing_personas=existing_personas,
        existing_scenarios=existing_scenarios,
        prs_with_changes_requested=prs_with_changes_requested,
        open_milestones=open_milestones,
    )


def _fetch_milestones(repo: str) -> list[dict[str, Any]]:
    """Fetch open GitHub milestones with issue counts."""
    try:
        raw = _gh(["api", f"repos/{repo}/milestones?state=open&per_page=100"], repo)
        milestones = json.loads(raw) if raw.strip() else []
    except (RuntimeError, json.JSONDecodeError):
        return []
    return milestones if isinstance(milestones, list) else []


def _fetch_discussions(repo: str) -> list[dict[str, Any]]:
    if "/" not in repo:
        return []
    owner, name = repo.split("/", 1)
    query = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    discussions(first:20, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        id
        number
        title
        body
        url
        category { name }
        comments(first:30) {
          nodes { author { login } body createdAt url }
        }
      }
    }
  }
}
"""
    try:
        raw = _gh(
            ["api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}", "-f", f"query={query}"],
            repo,
        )
        data = json.loads(raw)
    except (RuntimeError, json.JSONDecodeError):
        return []
    return (
        data.get("data", {})
        .get("repository", {})
        .get("discussions", {})
        .get("nodes", [])
        or []
    )


def resolve_priority(state: RepoState, repo: str) -> tuple[str, dict[str, Any]]:
    """Walk the priority list; return ``(priority_label, context_dict)``."""
    personas = _load_persona_index()

    if len(state.open_prs) >= 5:
        return "skip", {"reason": f"{len(state.open_prs)} PRs already open - avoid pile-up"}

    if state.prs_with_changes_requested:
        oldest = min(state.prs_with_changes_requested, key=lambda p: p["number"])
        return "address_changes_requested", _build_address_changes_context(repo, oldest, personas)

    review_context = _find_review_pr(repo, state, personas)
    if review_context:
        return "review_pr", review_context

    missing_required = _find_missing_required_reviewer(repo, state, personas)
    if missing_required:
        return "migrate_persona", {"persona_id": missing_required}

    rejected_context = _find_rejected_pr(repo, state, personas)
    if rejected_context:
        return "reject_pr", rejected_context

    merge_ready_context = _find_merge_ready_pr(repo, state, personas)
    if merge_ready_context:
        return "merge_pr", merge_ready_context

    accept_context = _find_accept_pr(repo, state, personas)
    if accept_context:
        return "accept_pr", accept_context

    merge_context = _find_merge_gate_pr(repo, state, personas)
    if merge_context:
        return "merge_gate", merge_context

    closable_issue = _find_closable_issue(state)
    if closable_issue:
        return "close_issue", {"issue": closable_issue}

    milestone_assignment = _find_issue_needing_milestone(state)
    if milestone_assignment:
        return "assign_milestone", {"issue": milestone_assignment}

    closable_milestone = _find_closable_milestone(state)
    if closable_milestone:
        return "close_milestone", {"milestone": closable_milestone}

    create_issue_context = _find_create_issue_request(state, personas)
    if create_issue_context:
        return "create_issue", create_issue_context

    next_persona = next(
        (p for p in _persona_catalog() if p not in state.existing_personas),
        None,
    )
    if next_persona:
        return "migrate_persona", {"persona_id": next_persona}

    next_scenario = next(
        (s for s in _scenario_catalog() if s not in state.existing_scenarios),
        None,
    )
    if next_scenario:
        return "implement_scenario", {"scenario_id": next_scenario}

    discussion = _find_discussion_to_comment(state, personas)
    if discussion:
        return "comment_discussion", {"discussion": discussion}

    closable_discussion = _find_discussion_to_close(state, personas)
    if closable_discussion:
        return "close_discussion", {"discussion": closable_discussion}

    audit_issue = _find_audit_issue(state)
    if audit_issue:
        return "run_audit", {"issue": audit_issue}

    triage_issue = _find_triage_issue(state)
    if triage_issue:
        return "triage_issue", {"issue": triage_issue}

    implementation_issue = _find_implementation_issue(state)
    if implementation_issue:
        return "implement_issue", {"issue": implementation_issue}

    return "post_status_and_exit", {}


def _find_review_pr(
    repo: str,
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    for pr in sorted(state.open_prs, key=lambda p: int(p["number"])):
        context = _build_review_context(repo, pr, state, personas)
        if context.get("persona_id"):
            return context
    return None


def _find_missing_required_reviewer(
    repo: str,
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> str | None:
    for pr in sorted(state.open_prs, key=lambda p: int(p["number"])):
        context = _build_review_context(repo, pr, state, personas)
        for reviewer in context.get("outstanding_reviewers") or []:
            if reviewer not in personas:
                return reviewer
    return None


def _build_review_context(
    repo: str,
    pr: dict[str, Any],
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any]:
    pr_number = int(pr["number"])
    details = _load_pr_details(repo, pr_number)
    details.update({key: value for key, value in pr.items() if key not in details})

    aliases = _persona_aliases(personas)
    required_reviewers = _reviewers_for_pr(details, personas, aliases)
    posted_reviewers, review_history = _review_history(details, aliases)
    outstanding = [p for p in required_reviewers if p not in posted_reviewers]

    if not required_reviewers:
        outstanding = _activated_personas_for_pr(details, personas)
        outstanding = [p for p in outstanding if p not in posted_reviewers]

    next_persona = next((p for p in outstanding if p in personas), None)
    changed_files = _changed_files(details)

    return {
        "pr": details,
        "persona_id": next_persona,
        "required_reviewers": required_reviewers,
        "posted_reviewers": posted_reviewers,
        "review_history": review_history,
        "outstanding_reviewers": outstanding,
        "changed_files": changed_files,
        "missing_personas": [
            p for p in _persona_catalog() if p not in state.existing_personas
        ],
        "scenarios_without_scorecards": [
            s for s in _scenario_catalog() if s not in state.existing_scenarios
        ],
    }


def _find_merge_gate_pr(
    repo: str,
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    gate_persona = _first_primary_persona_for_action("merge_gate", personas)
    if not gate_persona:
        return None
    for pr in sorted(state.open_prs, key=lambda p: int(p["number"])):
        context = _build_review_context(repo, pr, state, personas)
        if context.get("outstanding_reviewers"):
            continue
        if _latest_blocker(context["pr"]).get("body", "").startswith("No REQUEST_CHANGES"):
            context["persona_id"] = gate_persona
            return context
    return None


def _find_accept_pr(
    repo: str,
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    """Select a PR that passed Rhea's gate but lacks acceptance.

    The release flow is intentionally two-step: Rhea posts the release gate
    (`RHEA-VERDICT: MERGE_READY` or `RHEA-VERDICT: APPROVE`), then the
    acceptance persona posts `ACCEPTANCE-DECISION: ACCEPT`. `merge_pr` only
    fires after that second marker exists.
    """
    accept_persona = _first_primary_persona_for_action("accept_pr", personas)
    if not accept_persona:
        return None
    for pr in sorted(state.open_prs, key=lambda p: int(p["number"])):
        context = _build_review_context(repo, pr, state, personas)
        if context.get("outstanding_reviewers"):
            continue
        body = _combined_pr_thread_text(context["pr"])
        if _has_any_marker(body, ["ACCEPTANCE-DECISION: ACCEPT", "ACCEPTANCE-DECISION: REJECT"]):
            continue
        if _has_any_marker(body, ["RHEA-VERDICT: MERGE_READY", "RHEA-VERDICT: APPROVE", "MERGE-GATE: ACCEPT"]):
            context["persona_id"] = accept_persona
            return context
    return None

def _find_merge_ready_pr(
    repo: str,
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    merge_persona = _first_primary_persona_for_action("merge_pr", personas)
    if not merge_persona:
        return None
    for pr in sorted(state.open_prs, key=lambda p: int(p["number"])):
        context = _build_review_context(repo, pr, state, personas)
        if context.get("outstanding_reviewers"):
            continue
        body = _combined_pr_thread_text(context["pr"])
        if _has_any_marker(body, ["ACCEPTANCE-DECISION: ACCEPT"]):
            context["persona_id"] = merge_persona
            return context
    return None


def _find_rejected_pr(
    repo: str,
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    reject_persona = _first_primary_persona_for_action("reject_pr", personas)
    if not reject_persona:
        return None
    for pr in sorted(state.open_prs, key=lambda p: int(p["number"])):
        context = _build_review_context(repo, pr, state, personas)
        body = _combined_pr_thread_text(context["pr"])
        if _has_any_marker(body, ["ACCEPTANCE-DECISION: REJECT", "RHEA-VERDICT: REJECT", "FINAL-VERDICT: REJECT"]):
            context["persona_id"] = reject_persona
            return context
    return None


def _combined_pr_thread_text(pr: dict[str, Any]) -> str:
    parts: list[str] = [str(pr.get("body") or "")]
    for source_name in ("comments", "reviews"):
        for item in pr.get(source_name) or []:
            if isinstance(item, dict):
                parts.append(str(item.get("body") or ""))
                parts.append(str(item.get("state") or ""))
    return "\n".join(parts).upper()


def _has_any_marker(text: str, markers: list[str]) -> bool:
    upper = text.upper()
    return any(marker.upper() in upper for marker in markers)


def _find_closable_issue(state: RepoState) -> dict[str, Any] | None:
    terminal_labels = {
        "state:accepted", "state:done", "status:done", "status:complete",
        "resolution:accepted", "resolution:complete", "accepted", "done",
    }
    blocking_labels = {"blocked", "needs-review", "changes-requested", "ready-for-agent"}
    for issue in sorted(state.open_issues, key=lambda item: int(item["number"])):
        labels = set(_label_names(issue))
        if issue.get("number") == 1:
            continue
        if labels & terminal_labels and not (labels & blocking_labels):
            return issue
    return None


def _find_issue_needing_milestone(state: RepoState) -> dict[str, Any] | None:
    for issue in sorted(state.open_issues, key=lambda item: int(item["number"])):
        labels = set(_label_names(issue))
        if issue.get("number") == 1:
            continue
        if issue.get("milestone"):
            continue
        if "ready-for-agent" in labels or any(label.startswith("work:") for label in labels):
            return issue
    return None


def _find_closable_milestone(state: RepoState) -> dict[str, Any] | None:
    for milestone in sorted(state.open_milestones, key=lambda item: str(item.get("due_on") or item.get("title") or "")):
        if int(milestone.get("open_issues") or 0) == 0 and int(milestone.get("closed_issues") or 0) > 0:
            return milestone
    return None


def _find_create_issue_request(
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    """Find an explicit source marker that should become a new issue.

    This is the start point for real-world team requests. A human can add a
    marker such as `TEAM-REQUEST: Build a new feature to export invoices` to a
    Discussion or existing issue; the next loop converts it into one bounded
    `needs-triage` Issue, then future iterations triage and implement it.
    """
    actor = _first_primary_persona_for_action("create_issue", personas) or _first_primary_persona_for_action("open_issue", personas)
    if not actor:
        return None
    markers = ("CREATE-ISSUE:", "PROMOTE-TO-ISSUE:", "TEAM-REQUEST:")

    for discussion in state.open_discussions:
        if _discussion_has_terminal_marker(discussion):
            continue
        body = _discussion_text_blob(discussion)
        if any(marker in body for marker in markers):
            return {"source_kind": "discussion", "discussion": discussion, "persona_id": actor}

    for issue in sorted(state.open_issues, key=lambda item: int(item["number"])):
        if issue.get("number") == 1:
            continue
        body = str(issue.get("body") or "")
        labels = set(_label_names(issue))
        if "needs-followup-issue" in labels or any(marker in body for marker in markers):
            return {"source_kind": "issue", "issue": issue, "persona_id": actor}
    return None


def _find_discussion_to_close(
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    closer = _first_primary_persona_for_action("close_discussion", personas)
    if not closer:
        return None
    for discussion in state.open_discussions:
        if _discussion_has_terminal_marker(discussion):
            discussion["persona_id"] = closer
            discussion["node_id"] = discussion.get("node_id") or discussion.get("id")
            return discussion
    return None


def _load_pr_details(repo: str, pr_number: int) -> dict[str, Any]:
    raw = _gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,title,body,labels,author,headRefName,baseRefName,comments,reviews,files,url",
        ],
        repo,
    )
    return json.loads(raw) if raw.strip() else {}


def _build_address_changes_context(
    repo: str,
    pr: dict[str, Any],
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any]:
    details = _load_pr_details(repo, int(pr["number"]))
    details.update({key: value for key, value in pr.items() if key not in details})
    blocker = _latest_blocker(details)
    executor = _first_primary_persona_for_action("address_changes_requested", personas)
    return {
        "pr": details,
        "persona_id": executor,
        "blocker": blocker,
    }


def _latest_blocker(pr_details: dict[str, Any]) -> dict[str, str]:
    candidates: list[dict[str, Any]] = []
    for review in pr_details.get("reviews") or []:
        body = str(review.get("body") or "")
        state = str(review.get("state") or "")
        if state == "CHANGES_REQUESTED" or "REQUEST_CHANGES" in body or "BLOCKED" in body:
            candidates.append(review)
    for comment in pr_details.get("comments") or []:
        body = str(comment.get("body") or "")
        if "REQUEST_CHANGES" in body or "BLOCKED" in body:
            candidates.append(comment)

    if not candidates:
        return {
            "author": "unknown",
            "created_at": "unknown",
            "url": "",
            "body": "No REQUEST_CHANGES body found. Re-run `gh pr view --comments` and inspect manually.",
        }

    candidates.sort(key=lambda item: str(item.get("submittedAt") or item.get("createdAt") or ""))
    chosen = candidates[-1]
    author = chosen.get("author") or {}
    if isinstance(author, dict):
        author_name = str(author.get("login") or "unknown")
    else:
        author_name = str(author)
    return {
        "author": author_name,
        "created_at": str(chosen.get("submittedAt") or chosen.get("createdAt") or "unknown"),
        "url": str(chosen.get("url") or ""),
        "body": str(chosen.get("body") or "").strip(),
    }


def _find_audit_issue(state: RepoState) -> dict[str, Any] | None:
    for issue in sorted(state.open_issues, key=lambda item: int(item["number"])):
        labels = _label_names(issue)
        title = str(issue.get("title") or "").lower()
        body = str(issue.get("body") or "").lower()
        if "agent:audit" in labels or "audit" in title or "audit" in body:
            if "ready-for-agent" in labels or "work:system-improvement" in labels:
                return issue
    return None


def _find_triage_issue(state: RepoState) -> dict[str, Any] | None:
    for issue in sorted(state.open_issues, key=lambda item: int(item["number"])):
        labels = set(_label_names(issue))
        if issue.get("number") == 1:
            continue
        if "ready-for-agent" not in labels:
            return issue
    return None


def _find_implementation_issue(state: RepoState) -> dict[str, Any] | None:
    for issue in sorted(state.open_issues, key=lambda item: int(item["number"])):
        labels = set(_label_names(issue))
        if issue.get("number") == 1:
            continue
        if "ready-for-agent" in labels and "work:system-improvement" in labels:
            return issue
    return None


def _find_discussion_to_comment(
    state: RepoState,
    personas: dict[str, MarkdownDoc],
) -> dict[str, Any] | None:
    discussion_persona = _first_primary_persona_for_action("comment_discussion", personas)
    if not discussion_persona:
        return None
    aliases = _persona_aliases(personas)
    for discussion in state.open_discussions:
        category = (discussion.get("category") or {}).get("name") or ""
        title = str(discussion.get("title") or "")
        if category != "Idea Lab" and "idea" not in title.lower():
            continue
        comments = (discussion.get("comments") or {}).get("nodes") or []
        posted, _ = _review_history({"comments": comments, "reviews": []}, aliases)
        if _discussion_has_terminal_marker(discussion):
            continue
        if discussion_persona not in posted:
            discussion["persona_id"] = discussion_persona
            discussion["node_id"] = discussion.get("node_id") or discussion.get("id")
            return discussion
    return None


def _discussion_text_blob(discussion: dict[str, Any]) -> str:
    """Return title, body, and comments as one text blob for marker scans."""
    texts: list[str] = [str(discussion.get("title") or ""), str(discussion.get("body") or "")]
    comments = (discussion.get("comments") or {}).get("nodes") if isinstance(discussion.get("comments"), dict) else discussion.get("comments")
    for comment in comments or []:
        if isinstance(comment, dict):
            texts.append(str(comment.get("body") or ""))
    return "\n".join(texts)


def _discussion_has_terminal_marker(discussion: dict[str, Any]) -> bool:
    """Return True when a Discussion should not receive more bot comments."""
    terminal_tokens = {
        "DISCUSSION-STATE: CLOSED",
        "DISCUSSION-STATE: ANSWERED",
        "DISCUSSION-STATE: PROMOTED",
        "DISCUSSION-STATE: REJECTED",
        "IDEA-STATE: DIDNT-STICK",
        "IDEA-STATE: PROMOTED",
        "MAINTAINER-STOP",
        "HOLD",
        "BLOCKED",
    }
    texts: list[str] = [str(discussion.get("title") or ""), str(discussion.get("body") or "")]
    comments = (discussion.get("comments") or {}).get("nodes") or []
    for comment in comments:
        if isinstance(comment, dict):
            texts.append(str(comment.get("body") or ""))
    combined = "\n".join(texts).upper()
    return any(token in combined for token in terminal_tokens)


def _persona_aliases(personas: dict[str, MarkdownDoc]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for persona_id in _persona_catalog():
        aliases[persona_id] = persona_id
        aliases[persona_id.split("-", 1)[0]] = persona_id

    for persona_id, doc in personas.items():
        aliases[persona_id] = persona_id
        aliases[persona_id.split("-", 1)[0]] = persona_id
        name = str(doc.frontmatter.get("name") or "")
        if name:
            normalized = _normalize_persona_token(name)
            aliases[normalized] = persona_id
            aliases[normalized.split("-", 1)[0]] = persona_id
    return aliases


def _persona_action_ids(persona: MarkdownDoc, relation: str) -> list[str]:
    actions = persona.frontmatter.get("actions") or {}
    if not isinstance(actions, dict):
        return []
    return [str(action) for action in _as_list(actions.get(relation))]


def _personas_for_action(
    action_id: str,
    relation: str = "primary",
    personas: dict[str, MarkdownDoc] | None = None,
) -> list[str]:
    index = personas if personas is not None else _load_persona_index()
    matches: list[str] = []
    for persona_id, doc in sorted(index.items()):
        if action_id in _persona_action_ids(doc, relation):
            matches.append(persona_id)
    return matches


def _first_primary_persona_for_action(
    action_id: str,
    personas: dict[str, MarkdownDoc] | None = None,
) -> str | None:
    matches = _personas_for_action(action_id, "primary", personas)
    return matches[0] if matches else None


def _normalize_persona_token(value: str) -> str:
    value = re.sub(r"`|\*|_", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.split(r"\s+[--]\s+|\s+/\s+|:", value, maxsplit=1)[0]
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return value.strip("-")


def _reviewers_for_pr(
    pr: dict[str, Any],
    personas: dict[str, MarkdownDoc],
    aliases: dict[str, str],
) -> list[str]:
    reviewers = _parse_required_reviewers(str(pr.get("body") or ""), aliases)
    if not reviewers:
        reviewers = _activated_personas_for_pr(pr, personas)

    for reviewer in _policy_required_reviewers(_changed_files(pr)):
        if reviewer not in reviewers:
            reviewers.append(reviewer)
    return reviewers


def _parse_required_reviewers(body: str, aliases: dict[str, str]) -> list[str]:
    reviewers: list[str] = []
    in_required_section = False

    for line in body.splitlines():
        heading = line.strip().lower()
        if heading.startswith("## "):
            in_required_section = "required review" in heading or "required reviewer" in heading
            continue
        if not in_required_section:
            continue

        match = re.match(r"\s*-\s+(.+)$", line)
        if not match:
            continue
        token = _normalize_persona_token(match.group(1))
        persona_id = aliases.get(token) or aliases.get(token.split("-", 1)[0])
        if persona_id and persona_id not in reviewers:
            reviewers.append(persona_id)

    return reviewers


def _activated_personas_for_pr(
    pr: dict[str, Any],
    personas: dict[str, MarkdownDoc],
) -> list[str]:
    labels = set(_label_names(pr))
    activated: list[str] = []

    for persona_id in sorted(personas):
        doc = personas.get(persona_id)
        if not doc:
            continue
        if "review_pr" not in _persona_action_ids(doc, "primary") and "review_pr" not in _persona_action_ids(doc, "support"):
            continue
        triggers = doc.frontmatter.get("activates_on") or []
        if isinstance(triggers, str):
            triggers = [triggers]
        trigger_values = {str(trigger).strip() for trigger in triggers}
        if "*" in trigger_values or trigger_values.intersection(labels):
            activated.append(persona_id)
    return activated


def _review_history(
    pr: dict[str, Any],
    aliases: dict[str, str],
) -> tuple[list[str], list[dict[str, str]]]:
    posted: list[str] = []
    history: list[dict[str, str]] = []

    for source_name in ("comments", "reviews"):
        for item in pr.get(source_name) or []:
            body = str(item.get("body") or "")
            persona_id = _persona_from_body(body, aliases)
            if not persona_id:
                continue
            if persona_id not in posted:
                posted.append(persona_id)
            author = item.get("author") or {}
            author_login = author.get("login") if isinstance(author, dict) else str(author)
            history.append(
                {
                    "persona_id": persona_id,
                    "author": str(author_login or "unknown"),
                    "created_at": str(item.get("createdAt") or item.get("submittedAt") or "unknown"),
                    "verdict": _extract_verdict(body),
                    "url": str(item.get("url") or ""),
                }
            )
    return posted, history


def _persona_from_body(body: str, aliases: dict[str, str]) -> str | None:
    header_match = re.search(r"^Persona:\s*(.+)$", body, re.MULTILINE)
    if header_match:
        token = _normalize_persona_token(header_match.group(1))
        persona_id = aliases.get(token) or aliases.get(token.split("-", 1)[0])
        if persona_id:
            return persona_id

    first_line = body.strip().splitlines()[0] if body.strip() else ""
    for alias, persona_id in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", _normalize_persona_token(first_line)):
            return persona_id
    return None


def _extract_verdict(body: str) -> str:
    """Extract a persona verdict from modern or legacy review bodies.

    Older comments used ``**Verdict: APPROVE**`` while newer autonomous-loop
    templates require both ``REVIEW-VERDICT: APPROVE`` and
    ``**Verdict:** APPROVE``. The loop should count all of those shapes so a
    formatter tweak does not strand a PR in an infinite review cycle.
    """
    patterns = [
        r"^\s*REVIEW-VERDICT:\s*`?([^`\n]+)`?",
        r"\*\*(?:Final\s+)?[Vv]erdict:\s*`?([^*`\n]+)`?\*\*",
        r"\*\*(?:Final\s+)?[Vv]erdict:\*\*\s*`?([^`\n]+)`?",
        r"^##\s+(?:Final\s+)?[Vv]erdict:\s*`?([^`\n]+)`?",
        r"^\s*(?:Final\s+)?[Vv]erdict:\s*`?([^`\n]+)`?",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.MULTILINE)
        if match:
            verdict = match.group(1).strip().strip("*`:")
            return verdict.replace(" ", "_")
    return "UNKNOWN"


def _label_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for label in item.get("labels") or []:
        if isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
        elif isinstance(label, str):
            names.append(label)
    return names


def _policy_data() -> dict[str, Any]:
    return _load_yaml_file(POLICIES_PATH)


def _policy_required_reviewers(changed_files: list[str]) -> list[str]:
    policy = (_policy_data().get("operating_model_amendment") or {})
    if not _matches_any(changed_files, _operating_model_paths()):
        return []
    reviewers: list[str] = []
    for rule in policy.get("reviewer_rules") or []:
        if not isinstance(rule, dict):
            continue
        when_paths = [str(path) for path in _as_list(rule.get("when_paths"))]
        if "*" in when_paths or _matches_any(changed_files, when_paths):
            for reviewer in _as_list(rule.get("reviewers")):
                if reviewer not in reviewers:
                    reviewers.append(reviewer)
    return reviewers


def _policy_required_labels(changed_files: list[str]) -> list[str]:
    policy = (_policy_data().get("operating_model_amendment") or {})
    if not _matches_any(changed_files, _operating_model_paths()):
        return []
    return [str(label) for label in _as_list(policy.get("required_labels"))]


def _policy_check_block(pr: dict[str, Any], changed_files: list[str], required_reviewers: list[str]) -> str:
    labels = set(_label_names(pr))
    required_labels = _policy_required_labels(changed_files)
    policy_reviewers = _policy_required_reviewers(changed_files)
    if not required_labels and not policy_reviewers:
        return "No operating-model amendment policy matched this PR."

    label_rows = [
        f"- {label}: {'PASS' if label in labels else 'MISSING'}"
        for label in required_labels
    ] or ["- none"]
    reviewer_rows = [
        f"- {reviewer}: {'PRESENT' if reviewer in required_reviewers else 'MISSING'}"
        for reviewer in policy_reviewers
    ] or ["- none"]
    human_phrase = (
        (_policy_data().get("operating_model_amendment") or {})
        .get("required_human_phrase", "")
    )
    return (
        "Operating-model amendment policy matched changed paths.\n\n"
        "**Required labels:**\n"
        f"{chr(10).join(label_rows)}\n\n"
        "**Required reviewers from policy:**\n"
        f"{chr(10).join(reviewer_rows)}\n\n"
        f"**Required human phrase:** `{human_phrase or 'none'}`"
    )


def _changed_files(pr: dict[str, Any]) -> list[str]:
    files = pr.get("files") or []
    changed: list[str] = []
    for item in files:
        if isinstance(item, dict) and item.get("path"):
            changed.append(str(item["path"]))
        elif isinstance(item, str):
            changed.append(item)
    return changed


def render_prompt(
    repo: str,
    priority: str,
    context: dict[str, Any],
    state: RepoState,
    *,
    max_diff_chars: int = 24000,
    post_mode: str = "real",
) -> str:
    """Render a self-contained prompt from action templates and live state."""
    action_template = _load_action_template(priority)
    variables = _common_variables(repo, priority, state)
    variables["post_mode"] = post_mode
    variables.update(_action_variables(repo, priority, context, state, max_diff_chars=max_diff_chars))

    action_prompt = _render_template(action_template.body, variables)
    variables["action_prompt"] = action_prompt
    variables["hard_caps"] = _load_template_partial("_hard-caps.md", _fallback_hard_caps())
    variables["template_id"] = action_template.frontmatter.get("id", priority)
    variables["template_path"] = str(action_template.path.relative_to(REPO_ROOT))

    base = _load_template_partial("_base.md", _fallback_base_template())
    return _render_template(base, variables).strip() + "\n"


def _common_variables(repo: str, priority: str, state: RepoState) -> dict[str, Any]:
    missing_personas = [p for p in _persona_catalog() if p not in state.existing_personas]
    missing_scenarios = [s for s in _scenario_catalog() if s not in state.existing_scenarios]
    return {
        "repo": repo,
        "priority": priority,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "open_pr_count": len(state.open_prs),
        "open_issue_count": len(state.open_issues),
        "open_discussion_count": len(state.open_discussions),
        "open_milestone_count": len(state.open_milestones),
        "changes_requested_count": len(state.prs_with_changes_requested),
        "existing_personas": _format_inline_list(sorted(state.existing_personas)),
        "missing_personas": _format_inline_list(missing_personas),
        "existing_scenarios": _format_inline_list(sorted(state.existing_scenarios)),
        "scenarios_without_scorecards": _format_inline_list(missing_scenarios),
        "open_prs_table": _format_pr_table(state.open_prs),
        "open_issues_table": _format_issue_table(state.open_issues),
        "open_discussions_table": _format_discussion_table(state.open_discussions),
        "open_milestones_table": _format_milestone_table(state.open_milestones),
        "action_catalog_summary": _format_action_catalog_summary(),
    }


def _action_variables(
    repo: str,
    priority: str,
    context: dict[str, Any],
    state: RepoState,
    *,
    max_diff_chars: int,
) -> dict[str, Any]:
    if priority == "review_pr":
        return _review_variables(repo, context, max_diff_chars=max_diff_chars)
    if priority == "address_changes_requested":
        return _address_changes_variables(context)
    if priority == "merge_gate":
        return _merge_gate_variables(repo, context, max_diff_chars=max_diff_chars)
    if priority == "triage_issue":
        return _issue_variables(context, _first_primary_persona_for_action("triage_issue") or "auto-loop")
    if priority == "implement_issue":
        return _issue_variables(context, _first_primary_persona_for_action("implement_issue") or "auto-loop")
    if priority == "migrate_persona":
        return _migrate_persona_variables(context)
    if priority == "implement_scenario":
        return _scenario_variables(context)
    if priority == "run_audit":
        return _audit_variables(context)
    if priority == "comment_discussion":
        return _discussion_variables(context)
    if priority == "merge_pr":
        return _merge_gate_variables(repo, context, max_diff_chars=max_diff_chars)
    if priority in {"accept_pr", "reject_pr"}:
        return _merge_gate_variables(repo, context, max_diff_chars=max_diff_chars)
    if priority in {"open_issue", "create_issue", "close_issue", "reopen_issue", "assign_milestone"}:
        return _issue_lifecycle_variables(context, priority)
    if priority in {"create_milestone", "close_milestone"}:
        return _milestone_variables(context, priority)
    if priority in {"request_review", "resolve_review_thread", "verify_agent_action"}:
        return _generic_action_variables(context, priority)
    if priority == "close_discussion":
        return _discussion_variables(context)
    if priority in {
        "prompt_improvement",
        "run_prompt_regression",
        "security_audit",
        "cost_review",
        "generate_ideas",
        "promote_idea",
        "open_followup_issue",
        "decision_record",
        "retrospective",
        "knowledge_update",
        "re_ratification",
    }:
        return _generic_action_variables(context, priority)
    if priority == "skip":
        return {"skip_reason": context["reason"], **_status_persona_variables("skip")}
    if priority == "post_status_and_exit":
        return {
            "status_reason": "No priority action is currently available.",
            **_status_persona_variables("post_status_and_exit"),
        }
    raise RuntimeError(f"unknown priority: {priority}")


def _review_variables(
    repo: str,
    context: dict[str, Any],
    *,
    max_diff_chars: int,
) -> dict[str, Any]:
    pr = context["pr"]
    persona_id = context["persona_id"]
    if persona_id is None:
        raise RuntimeError("review_pr selected without a persona_id")

    persona = _require_persona(persona_id)
    frontmatter = persona.frontmatter
    preamble = _load_preamble() if frontmatter.get("inherits_preamble") else ""
    changed_files = context.get("changed_files") or []
    required_reviewers = context.get("required_reviewers") or []
    diff = _gh(["pr", "diff", str(pr["number"])], repo).strip()
    diff_note = "Full diff included."
    if max_diff_chars > 0 and len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + "\n\n...diff truncated by next_prompt; run the Step 2 command for the full diff..."
        diff_note = f"Diff truncated at {max_diff_chars} characters; Step 2 fetches the full diff."

    return {
        "pr_number": pr["number"],
        "pr_title": pr.get("title") or "",
        "pr_url": pr.get("url") or f"https://github.com/{repo}/pull/{pr['number']}",
        "pr_body": pr.get("body") or "",
        "pr_summary": _first_nonempty_line(pr.get("body") or "No PR body available."),
        "pr_labels": _format_inline_list(_label_names(pr)),
        "pr_author": _author_login(pr),
        "pr_head_ref": pr.get("headRefName") or "",
        "pr_base_ref": pr.get("baseRefName") or "",
        "pr_changed_files": _format_bullets(changed_files),
        "pr_changed_files_inline": _format_inline_list(changed_files),
        "pr_diff": diff,
        "pr_diff_note": diff_note,
        "linked_issue_context": _linked_issue_context(repo, pr),
        "persona_context_pack": _persona_context_pack(persona_id),
        "required_reviewers": _format_inline_list(required_reviewers),
        "policy_check": _policy_check_block(pr, changed_files, required_reviewers),
        "posted_reviewers": _format_inline_list(context.get("posted_reviewers") or []),
        "outstanding_reviewers": _format_inline_list(context.get("outstanding_reviewers") or []),
        "review_history": _format_review_history(context.get("review_history") or []),
        "next_reviewer_persona": _next_reviewer_after_current(
            persona_id,
            context.get("outstanding_reviewers") or [],
        ),
        "self_review_conflict": _self_review_conflict(frontmatter, changed_files),
        **_persona_variables(persona),
    }


def _merge_gate_variables(
    repo: str,
    context: dict[str, Any],
    *,
    max_diff_chars: int,
) -> dict[str, Any]:
    values = _review_variables(repo, context, max_diff_chars=max_diff_chars)
    return values


def _address_changes_variables(context: dict[str, Any]) -> dict[str, Any]:
    pr = context["pr"]
    blocker = context.get("blocker") or {}
    persona_id = context.get("persona_id")
    persona_vars = _persona_variables(_require_persona(persona_id)) if persona_id else _anonymous_persona()
    return {
        "pr_number": pr["number"],
        "pr_title": pr.get("title") or "",
        "pr_url": pr.get("url") or "",
        "blocker_author": blocker.get("author") or "unknown",
        "blocker_created_at": blocker.get("created_at") or "unknown",
        "blocker_url": blocker.get("url") or "",
        "blocker_body": blocker.get("body") or "",
        **persona_vars,
    }


def _issue_lifecycle_variables(context: dict[str, Any], action_id: str) -> dict[str, Any]:
    issue = context.get("issue") or {}
    discussion = context.get("discussion") or {}
    source = issue or discussion
    source_kind = context.get("source_kind") or ("issue" if issue else "discussion" if discussion else "manual")
    source_body = str(source.get("body") or "")
    source_title = str(source.get("title") or "")
    persona_id = _first_primary_persona_for_action(action_id) or _first_primary_persona_for_action("triage_issue")
    persona_vars = _persona_variables(_require_persona(persona_id)) if persona_id else _anonymous_persona()
    proposed_title = _first_nonempty_line(source_body)
    for marker in ("CREATE-ISSUE:", "PROMOTE-TO-ISSUE:", "TEAM-REQUEST:"):
        proposed_title = proposed_title.replace(marker, "").strip()
    return {
        "issue_number": issue.get("number") or "[ISSUE_NUMBER]",
        "issue_title": issue.get("title") or "[ISSUE_TITLE]",
        "issue_body": issue.get("body") or "[ISSUE_BODY]",
        "issue_labels": _format_inline_list(_label_names(issue)) if issue else "none",
        "issue_milestone": _issue_milestone_title(issue),
        "target_milestone_title": _target_milestone_title(issue),
        "source_kind": source_kind,
        "source_number": source.get("number") or "[SOURCE_NUMBER]",
        "source_title": source_title or "[SOURCE_TITLE]",
        "source_body": source_body or "[SOURCE_BODY]",
        "source_url": source.get("url") or "[SOURCE_URL]",
        "proposed_issue_title": proposed_title or source_title or "[ISSUE_TITLE]",
        "action_id": action_id,
        **persona_vars,
    }


def _milestone_variables(context: dict[str, Any], action_id: str) -> dict[str, Any]:
    milestone = context.get("milestone") or {}
    persona_id = _first_primary_persona_for_action(action_id) or _first_primary_persona_for_action("triage_issue")
    persona_vars = _persona_variables(_require_persona(persona_id)) if persona_id else _anonymous_persona()
    return {
        "milestone_number": milestone.get("number") or "[MILESTONE_NUMBER]",
        "milestone_title": milestone.get("title") or "[MILESTONE_TITLE]",
        "milestone_description": milestone.get("description") or "",
        "milestone_due_on": milestone.get("due_on") or "",
        "milestone_open_issues": milestone.get("open_issues") or 0,
        "milestone_closed_issues": milestone.get("closed_issues") or 0,
        "action_id": action_id,
        **persona_vars,
    }


def _issue_milestone_title(issue: dict[str, Any]) -> str:
    milestone = issue.get("milestone") or {}
    return str(milestone.get("title") or "none") if isinstance(milestone, dict) else str(milestone or "none")


def _target_milestone_title(issue: dict[str, Any]) -> str:
    labels = set(_label_names(issue))
    for label in labels:
        if label.startswith("milestone:"):
            return label.split(":", 1)[1].strip() or "[MILESTONE_TITLE]"
    return "[MILESTONE_TITLE]"


def _issue_variables(context: dict[str, Any], persona_id: str) -> dict[str, Any]:
    issue = context["issue"]
    persona_vars = _persona_variables(_require_persona(persona_id)) if (AGENT_PROMPTS_DIR / f"{persona_id}.md").exists() else _anonymous_persona()
    return {
        "issue_number": issue.get("number") or "",
        "issue_title": issue.get("title") or "",
        "issue_body": issue.get("body") or "",
        "issue_labels": _format_inline_list(_label_names(issue)),
        **persona_vars,
    }


def _migrate_persona_variables(context: dict[str, Any]) -> dict[str, Any]:
    persona_id = context["persona_id"]
    actor_id = _first_primary_persona_for_action("migrate_persona")
    actor_vars = _persona_variables(_require_persona(actor_id)) if actor_id else _anonymous_persona()
    return {
        "target_persona_id": persona_id,
        "target_persona_name": _persona_name_from_id(persona_id),
        "target_persona_role": _persona_role_from_id(persona_id),
        "target_persona_lens": _persona_lens_from_id(persona_id),
        "persona_frontmatter_contract": _extract_frontmatter_contract(),
        "persona_reference_files": _format_bullets(_reference_persona_files()),
        "preamble_text": _load_preamble(),
        **actor_vars,
    }


def _scenario_variables(context: dict[str, Any]) -> dict[str, Any]:
    scenario_id = context["scenario_id"]
    schema_path = REPO_ROOT / "simulation" / "scenarios" / "_schema.yml"
    example_path = REPO_ROOT / "simulation" / "scenarios" / "001-suspend-cookie.yml"
    actor_id = _first_primary_persona_for_action("implement_scenario")
    actor_vars = _persona_variables(_require_persona(actor_id)) if actor_id else _anonymous_persona()
    return {
        "scenario_id": scenario_id,
        "scenario_schema": _read_optional(schema_path),
        "scenario_example": _read_optional(example_path),
        **actor_vars,
    }


def _audit_variables(context: dict[str, Any]) -> dict[str, Any]:
    issue = context["issue"]
    actor_id = _first_primary_persona_for_action("run_audit")
    actor_vars = _persona_variables(_require_persona(actor_id)) if actor_id else _anonymous_persona()
    return {
        "audit_issue_number": issue.get("number") or "",
        "audit_issue_title": issue.get("title") or "",
        "audit_issue_body": issue.get("body") or "",
        "audit_issue_labels": _format_inline_list(_label_names(issue)),
        **actor_vars,
    }


def _generic_action_variables(context: dict[str, Any], action_id: str) -> dict[str, Any]:
    persona_id = _first_primary_persona_for_action(action_id)
    persona_vars = _persona_variables(_require_persona(persona_id)) if persona_id else _anonymous_persona()
    issue = context.get("issue") or {}
    pr = context.get("pr") or {}
    return {
        "source_issue_number": issue.get("number") or "[ISSUE_NUMBER]",
        "source_issue_title": issue.get("title") or "[ISSUE_TITLE]",
        "source_issue_body": issue.get("body") or "[ISSUE_BODY]",
        "source_issue_labels": _format_inline_list(_label_names(issue)) if issue else "none",
        "source_pr_number": pr.get("number") or "[PR_NUMBER]",
        "source_pr_title": pr.get("title") or "[PR_TITLE]",
        "action_id": action_id,
        **persona_vars,
    }


def _status_persona_variables(action_id: str) -> dict[str, Any]:
    persona_id = _first_primary_persona_for_action(action_id)
    return _persona_variables(_require_persona(persona_id)) if persona_id else _anonymous_persona()


def _discussion_variables(context: dict[str, Any]) -> dict[str, Any]:
    discussion = context.get("discussion") or {}
    persona_id = discussion.get("persona_id") or _first_primary_persona_for_action("comment_discussion")
    persona_vars = _persona_variables(_require_persona(persona_id)) if persona_id else _anonymous_persona()
    return {
        "discussion_number": discussion.get("number") or "[DISCUSSION_NUMBER]",
        "discussion_node_id": discussion.get("node_id") or discussion.get("id") or "[DISCUSSION_NODE_ID]",
        "discussion_title": discussion.get("title") or "[DISCUSSION_TITLE]",
        "discussion_body": discussion.get("body") or "[DISCUSSION_BODY]",
        "discussion_url": discussion.get("url") or "[DISCUSSION_URL]",
        **persona_vars,
    }


def _persona_variables(persona: MarkdownDoc) -> dict[str, Any]:
    fm = persona.frontmatter
    output_section = _extract_section(persona.body, "Output")
    comment_template = _persona_comment_template(fm, output_section)
    return {
        "persona_id": fm.get("id") or persona.path.stem,
        "persona_name": fm.get("name") or _persona_name_from_id(persona.path.stem),
        "persona_role": fm.get("role") or _persona_role_from_id(persona.path.stem),
        "persona_layer": fm.get("layer") or "knowledge",
        "persona_lens": fm.get("lens") or "",
        "persona_model_default": fm.get("model_default") or "unspecified",
        "persona_verdict_enum": _format_inline_list(_as_list(fm.get("verdict_enum"))),
        "persona_forbidden_paths": _format_bullets(_as_list(fm.get("forbidden_paths"))),
        "persona_prompt": persona.body,
        "persona_output_section": output_section or "No ## Output section found in persona prompt.",
        "persona_comment_template": comment_template,
        "inherits_preamble": _load_preamble() if fm.get("inherits_preamble") else "",
        "persona_prompt_path": str(persona.path.relative_to(REPO_ROOT)),
        "persona_action_menu": _format_persona_action_menu(str(fm.get("id") or persona.path.stem)),
    }


def _persona_comment_template(frontmatter: dict[str, Any], output_section: str) -> str:
    if frontmatter.get("inherits_preamble"):
        return (
            "REVIEW-VERDICT: CHANGE_ME\n\n"
            "**Verdict:** CHANGE_ME\n\n"
            "**Acceptance matrix:**\n"
            "| Criterion | Status | Evidence (path:line or MISSING) |\n"
            "| --- | --- | --- |\n"
            "| CHANGE_ME | CHANGE_ME | CHANGE_ME |\n\n"
            "**Blocking findings:**\n"
            "1. CHANGE_ME or `none`\n\n"
            "**Non-blocking findings:**\n"
            "1. CHANGE_ME or `none`\n\n"
            "**Persona-specific assessment:**\n"
            "CHANGE_ME\n\n"
            "**Required next action:** CHANGE_ME\n\n"
            "**Fallibility statement:** This review may be wrong; verify against the diff, CI, and the issue acceptance criteria."
        )
    return _extract_first_code_block(output_section) or output_section or "CHANGE_ME"


def _anonymous_persona() -> dict[str, Any]:
    return {
        "persona_id": "auto-loop",
        "persona_name": "Autonomous Loop",
        "persona_role": "Autonomous Loop Dispatcher",
        "persona_layer": "knowledge",
        "persona_lens": "loop-continuity",
        "persona_model_default": "n/a",
        "persona_verdict_enum": "COMMENT",
        "persona_forbidden_paths": "- n/a",
        "persona_prompt": "",
        "persona_output_section": "",
        "persona_comment_template": "",
        "inherits_preamble": "",
        "persona_prompt_path": "n/a",
        "persona_action_menu": "- No persona prompt was available for this action.",
    }


def _require_persona(persona_id: str | None) -> MarkdownDoc:
    if not persona_id:
        raise RuntimeError("missing persona id")
    personas = _load_persona_index()
    if persona_id not in personas:
        raise RuntimeError(f"missing persona prompt: .github/agent-prompts/{persona_id}.md")
    return personas[persona_id]


def _load_preamble() -> str:
    path = AGENT_PROMPTS_DIR / "_preamble.md"
    return _read_optional(path)


def _self_review_conflict(frontmatter: dict[str, Any], changed_files: list[str]) -> str:
    forbidden = _as_list(frontmatter.get("forbidden_paths"))
    if _matches_any(changed_files, forbidden) or _matches_any(changed_files, _operating_model_paths()):
        return "Yes"
    return "No"


def _matches_any(paths: list[str], patterns: list[str]) -> bool:
    for path in paths:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
    return False


def _next_reviewer_after_current(current: str, outstanding: list[str]) -> str:
    if current not in outstanding:
        return "Run next_prompt again after posting; it will re-read GitHub state."
    index = outstanding.index(current)
    remaining = outstanding[index + 1 :]
    return remaining[0] if remaining else "None from current outstanding list."


def _format_inline_list(values: list[Any] | set[Any] | tuple[Any, ...]) -> str:
    cleaned = [str(value) for value in values if str(value)]
    return ", ".join(cleaned) if cleaned else "none"


def _format_bullets(values: list[Any] | set[Any] | tuple[Any, ...]) -> str:
    cleaned = [str(value) for value in values if str(value)]
    if not cleaned:
        return "- none"
    return "\n".join(f"- {value}" for value in cleaned)


def _format_review_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "- none"
    rows = []
    for item in history:
        suffix = f" - {item['url']}" if item.get("url") else ""
        rows.append(
            f"- {item['persona_id']} by @{item['author']} at {item['created_at']}: "
            f"{item['verdict']}{suffix}"
        )
    return "\n".join(rows)


def _format_pr_table(prs: list[dict[str, Any]]) -> str:
    if not prs:
        return "| PR | Title | Labels | Review decision |\n| --- | --- | --- | --- |\n| none | none | none | none |"
    rows = ["| PR | Title | Labels | Review decision |", "| --- | --- | --- | --- |"]
    for pr in prs:
        rows.append(
            f"| #{pr.get('number')} | {_escape_table(pr.get('title') or '')} | "
            f"{_escape_table(_format_inline_list(_label_names(pr)))} | "
            f"{_escape_table(pr.get('reviewDecision') or 'none')} |"
        )
    return "\n".join(rows)


def _format_issue_table(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "| Issue | Title | Labels |\n| --- | --- | --- |\n| none | none | none |"
    rows = ["| Issue | Title | Labels |", "| --- | --- | --- |"]
    for issue in issues[:20]:
        rows.append(
            f"| #{issue.get('number')} | {_escape_table(issue.get('title') or '')} | "
            f"{_escape_table(_format_inline_list(_label_names(issue)))} |"
        )
    if len(issues) > 20:
        rows.append(f"| ... | {len(issues) - 20} more issues omitted | ... |")
    return "\n".join(rows)


def _format_discussion_table(discussions: list[dict[str, Any]]) -> str:
    if not discussions:
        return "| Discussion | Category | Title |\n| --- | --- | --- |\n| none | none | none |"
    rows = ["| Discussion | Category | Title |", "| --- | --- | --- |"]
    for discussion in discussions[:10]:
        category = (discussion.get("category") or {}).get("name") or "none"
        rows.append(
            f"| #{discussion.get('number')} | {_escape_table(category)} | "
            f"{_escape_table(discussion.get('title') or '')} |"
        )
    if len(discussions) > 10:
        rows.append(f"| ... | ... | {len(discussions) - 10} more discussions omitted |")
    return "\n".join(rows)


def _format_milestone_table(milestones: list[dict[str, Any]]) -> str:
    if not milestones:
        return "| Milestone | Due | Open | Closed |\n| --- | --- | --- | --- |\n| none | none | 0 | 0 |"
    rows = ["| Milestone | Due | Open | Closed |", "| --- | --- | --- | --- |"]
    for milestone in milestones[:20]:
        rows.append(
            f"| #{milestone.get('number')} {_escape_table(milestone.get('title') or '')} | "
            f"{_escape_table(milestone.get('due_on') or 'none')} | "
            f"{milestone.get('open_issues') or 0} | {milestone.get('closed_issues') or 0} |"
        )
    if len(milestones) > 20:
        rows.append(f"| ... | {len(milestones) - 20} more milestones omitted | ... | ... |")
    return "\n".join(rows)


def _format_action_catalog_summary() -> str:
    actions = _load_action_catalog()
    if not actions:
        return "| Action | Class | Template | Primary personas | Mutates |\n| --- | --- | --- | --- | --- |\n| none | none | none | none | none |"
    rows = ["| Action | Class | Template | Primary personas | Mutates |", "| --- | --- | --- | --- | --- |"]
    for action in actions:
        action_id = str(action.get("id") or "")
        primary = _personas_for_action(action_id, "primary")
        rows.append(
            f"| `{action.get('id')}` | {_escape_table(action.get('class') or '')} | "
            f"`{action.get('template')}` | "
            f"{_escape_table(_format_inline_list(primary))} | "
            f"{_escape_table(str(action.get('mutates') or 'read_only'))} |"
        )
    return "\n".join(rows)


def _format_persona_action_menu(persona_id: str) -> str:
    actions = _load_action_catalog()
    selected: list[dict[str, Any]] = []
    persona = _load_persona_index().get(persona_id)
    primary_actions = set(_persona_action_ids(persona, "primary")) if persona else set()
    support_actions = set(_persona_action_ids(persona, "support")) if persona else set()
    for action in actions:
        action_id = str(action.get("id") or "")
        if action_id in primary_actions or action_id in support_actions:
            selected.append(action)

    if not selected:
        return "- No catalog actions currently list this persona."

    blocks: list[str] = []
    for action in selected:
        action_id = str(action.get("id") or "")
        relation = "primary" if action_id in primary_actions else "support"
        steps = _format_bullets(action.get("compact_steps") or [])
        blocks.append(
            f"### `{action.get('id')}` ({relation}, {action.get('class')})\n"
            f"- Template: `.github/action-templates/{action.get('template')}`\n"
            f"- Mutates: {action.get('mutates') or 'read_only'}\n"
            f"- When: {action.get('when') or 'No trigger documented.'}\n"
            f"- Compact steps:\n{steps}"
        )
    return "\n\n".join(blocks)


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple) or isinstance(value, set):
        return [str(item) for item in value]
    return [str(value)]


def _author_login(pr: dict[str, Any]) -> str:
    author = pr.get("author") or {}
    if isinstance(author, dict):
        return str(author.get("login") or "unknown")
    return str(author)


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _linked_issue_numbers(text: str) -> list[int]:
    numbers: list[int] = []
    patterns = [
        r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
        r"(?:issue|epic)\s+#(\d+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            number = int(match.group(1))
            if number not in numbers:
                numbers.append(number)
    return numbers


def _linked_issue_context(repo: str, pr: dict[str, Any]) -> str:
    numbers = _linked_issue_numbers(str(pr.get("body") or ""))
    if not numbers:
        return "No linked issue number found in PR body."

    sections: list[str] = []
    for number in numbers[:3]:
        try:
            raw = _gh(
                ["issue", "view", str(number), "--json", "number,title,body,labels,url"],
                repo,
            )
            issue = json.loads(raw)
        except (RuntimeError, json.JSONDecodeError):
            sections.append(f"## Issue #{number}\nCould not fetch this issue with gh.")
            continue
        sections.append(
            f"## Issue #{issue.get('number')} - {issue.get('title')}\n"
            f"URL: {issue.get('url')}\n"
            f"Labels: {_format_inline_list(_label_names(issue))}\n\n"
            f"{issue.get('body') or ''}"
        )
    return "\n\n---\n\n".join(sections)


def _persona_context_pack(persona_id: str, action_id: str = "review_pr") -> str:
    persona = _require_persona(persona_id)
    refs = persona.frontmatter.get("context_refs") or {}
    paths = refs.get(action_id) if isinstance(refs, dict) else []
    snippets: list[str] = []
    for raw_path in _as_list(paths):
        path = REPO_ROOT / raw_path
        text = _read_optional(path)
        snippets.append(f"## `{raw_path}`\n\n```markdown\n{text}\n```")
    return "\n\n".join(snippets) if snippets else "No persona-specific context refs declared."


def _read_optional(path: Path) -> str:
    if not path.exists():
        return f"[missing: {path.relative_to(REPO_ROOT)}]"
    return path.read_text().strip()


def _extract_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    return match.group("body").strip() if match else ""


def _extract_first_code_block(markdown: str) -> str:
    match = re.search(r"```[a-zA-Z0-9_-]*\n(?P<body>.*?)\n```", markdown, re.DOTALL)
    return match.group("body").strip() if match else ""


def _extract_frontmatter_contract() -> str:
    readme = AGENT_PROMPTS_DIR / "README.md"
    text = _read_optional(readme)
    section = _extract_section(text, "Frontmatter contract (every persona file)")
    return _extract_first_code_block(section) or section or "No frontmatter contract found."


def _reference_persona_files() -> list[str]:
    return [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(AGENT_PROMPTS_DIR.glob("*.md"))
        if not path.name.startswith("_") and path.name != "README.md"
    ][:3]


def _persona_name_from_id(persona_id: str) -> str:
    return persona_id.split("-", 1)[0].capitalize()


def _persona_role_from_id(persona_id: str) -> str:
    pieces = persona_id.split("-")[1:] or ["agent"]
    return "AI " + " ".join(piece.capitalize() for piece in pieces)


def _persona_lens_from_id(persona_id: str) -> str:
    pieces = persona_id.split("-")[1:] or [persona_id]
    return " / ".join(pieces)


def _render_template(template: str, variables: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in variables:
            raise RuntimeError(f"template variable not provided: {key}")
        return str(variables[key])

    return re.sub(r"{{\s*([a-zA-Z0-9_]+)\s*}}", replace, template)


def validate_rendered_prompt(prompt: str) -> list[str]:
    """Return render errors for the final generated prompt.

    GitHub Actions diffs may legitimately include expressions such as
    ``${{ github.actor }}``, so unresolved-template detection ignores braces
    preceded by ``$`` and only catches next_prompt's own ``{{ variable }}``
    placeholders.
    """
    errors: list[str] = []
    unresolved = sorted(set(re.findall(r"(?<!\$){{\s*[a-zA-Z0-9_]+\s*}}", prompt)))
    if unresolved:
        errors.append("unresolved template variables: " + ", ".join(unresolved))
    required_fragments = ["# Autonomous loop", "Hard Caps", "Step"]
    for fragment in required_fragments:
        if fragment not in prompt:
            errors.append(f"rendered prompt missing required fragment: {fragment}")
    return errors


def validate_static_config() -> list[str]:
    """Validate templates, catalog, policy, persona frontmatter, and action ids.

    This check performs no GitHub calls, so it can run in CI or this ChatGPT
    container before a live ``gh``-backed run.
    """
    errors: list[str] = []

    actions = _load_action_catalog()
    action_ids: set[str] = set()
    if not actions:
        errors.append("missing or empty .github/action-templates/catalog.yml")
    for action in actions:
        if not isinstance(action, dict):
            errors.append("action catalog contains a non-object entry")
            continue
        action_id = str(action.get("id") or "").strip()
        template = str(action.get("template") or "").strip()
        if not action_id:
            errors.append("action catalog entry missing id")
            continue
        if action_id in action_ids:
            errors.append(f"duplicate action id: {action_id}")
        action_ids.add(action_id)
        if not template:
            errors.append(f"action {action_id} missing template")
        elif not (ACTION_TEMPLATES_DIR / template).exists():
            errors.append(f"action {action_id} references missing template: {template}")

    from simulation.tools import marker_registry

    errors.extend(marker_registry.validate_catalog_coverage(action_ids))
    marker_specs = marker_registry.load_marker_specs()
    for action_id, spec in marker_specs.items():
        template_name = _template_name_for_action(action_id)
        template_path = ACTION_TEMPLATES_DIR / template_name
        if template_path.exists():
            text = template_path.read_text()
            if spec.marker not in text:
                errors.append(f"action {action_id} template does not mention marker {spec.marker}:")

    personas = _load_persona_index()
    for persona_id in _persona_catalog():
        if persona_id not in personas:
            errors.append(f"roster persona missing prompt: {persona_id}")

    required_frontmatter = {
        "id", "name", "role", "layer", "version", "model_default", "lens",
        "verdict_enum", "activates_on", "actions", "forbidden_paths",
        "context_pack", "inherits_preamble", "owner",
    }
    for persona_id, doc in personas.items():
        missing = sorted(key for key in required_frontmatter if key not in doc.frontmatter)
        if missing:
            errors.append(f"persona {persona_id} missing frontmatter: {', '.join(missing)}")
        actions_block = doc.frontmatter.get("actions") or {}
        if not isinstance(actions_block, dict):
            errors.append(f"persona {persona_id} actions must be a mapping")
            continue
        for relation in ("primary", "support"):
            for action_id in _as_list(actions_block.get(relation)):
                if action_ids and action_id not in action_ids:
                    errors.append(f"persona {persona_id} references unknown {relation} action: {action_id}")
        refs = doc.frontmatter.get("context_refs") or {}
        if isinstance(refs, dict):
            for action_id, paths in refs.items():
                if action_ids and str(action_id) not in action_ids:
                    errors.append(f"persona {persona_id} has context_refs for unknown action: {action_id}")
                for raw_path in _as_list(paths):
                    if raw_path.startswith("http") or raw_path.startswith("["):
                        continue
                    if not (REPO_ROOT / raw_path).exists():
                        errors.append(f"persona {persona_id} context ref missing: {raw_path}")

    scenarios = _scenario_catalog()
    if "catalog" in scenarios:
        errors.append("scenario catalog must not include catalog")
    return errors


def _fallback_base_template() -> str:
    return (
        "# Autonomous loop - next iteration ({{priority}})\n\n"
        "Generated at {{generated_at}} by `simulation/tools/next_prompt.py` from live state of "
        "`{{repo}}` and repository-owned templates.\n\n"
        "{{action_prompt}}\n\n"
        "{{hard_caps}}\n"
    )


def _fallback_hard_caps() -> str:
    return (
        "## Hard caps (NON-NEGOTIABLE)\n\n"
        "- Max 3 file writes per iteration.\n"
        "- Max 2 sub-agent dispatches.\n"
        "- Max 6 Bash calls.\n"
        "- Per-iteration budget ceiling: $5.00.\n"
        "- Never bypass commit hooks (`--no-verify`, `SKIP_TESTS=1`).\n"
        "- Never run destructive git ops (`rm -rf`, `push --force`).\n"
        "- Sign every comment with the v0.3 YAML persona header.\n"
        "- Every commit ends with a `Co-Authored-By:` trailer naming your model.\n"
        "- Post end-of-run summary as a comment on Epic #1.\n"
    )


def _context_for_probe(context: dict[str, Any]) -> dict[str, Any]:
    """Trim noisy context for --probe-only output."""
    trimmed: dict[str, Any] = {}
    for key, value in context.items():
        if key in {"pr", "issue"} and isinstance(value, dict):
            trimmed[key] = {
                "number": value.get("number"),
                "title": value.get("title"),
                "labels": _label_names(value),
            }
        elif key == "review_history":
            trimmed[key] = value
        else:
            trimmed[key] = value
    return trimmed


def main() -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="ci4me/ai-erp-foundation")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write prompt to this file instead of stdout.",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Print the resolved priority + context, skip the prompt body.",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=24000,
        help="Maximum PR diff characters embedded in the prompt; 0 means no limit.",
    )
    parser.add_argument(
        "--post-mode",
        choices=["real", "dry-run"],
        default="real",
        help="Render mutation steps as real commands or dry-run echo commands.",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate templates, policies, roster, personas, and action ids without gh.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=1,
        help=(
            "Render N consecutive ticks (chaining via CHAIN-NEXT honored). "
            "Default 1 keeps the historic single-prompt behavior."
        ),
    )
    args = parser.parse_args()

    if args.validate_config:
        errors = validate_static_config()
        if errors:
            print("CONFIG INVALID:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 2
        print("CONFIG OK")
        return 0

    if not shutil.which("gh"):
        print("ERROR: gh CLI not found in PATH.", file=sys.stderr)
        return 2

    try:
        state = gather_repo_state(args.repo)
        priority, context = resolve_priority(state, args.repo)
        if args.probe_only:
            print(f"priority: {priority}")
            print(f"context: {json.dumps(_context_for_probe(context), indent=2, default=str)}")
            print(f"open_prs: {len(state.open_prs)}")
            print(f"changes_requested: {len(state.prs_with_changes_requested)}")
            print(f"existing_personas: {sorted(state.existing_personas)}")
            print(f"existing_scenarios: {sorted(state.existing_scenarios)}")
            return 0

        prompt = render_prompt(
            args.repo,
            priority,
            context,
            state,
            max_diff_chars=args.max_diff_chars,
            post_mode=args.post_mode,
        )
        prompt_errors = validate_rendered_prompt(prompt)
        if prompt_errors:
            raise RuntimeError("rendered prompt failed validation: " + "; ".join(prompt_errors))
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.max_iterations > 1:
        # Multi-iteration mode renders N consecutive prompts. Real chaining
        # (CHAIN-NEXT) is realised at the *agent* layer because this CLI
        # only writes prompts; the wrapper that follows CHAIN-NEXT inline
        # is simulation.tools.loop_runner.run_iterations.
        base = args.output or Path("/tmp/next_prompt_iter.md")
        base.parent.mkdir(parents=True, exist_ok=True)
        first = base.with_suffix(".1.md") if base.suffix else base.with_name(base.name + ".1")
        first.write_text(prompt)
        print(
            f"iteration 1/{args.max_iterations} rendered to {first}. "
            f"For each subsequent iteration the agent should execute the action, "
            f"check the posted body for CHAIN-NEXT, and re-invoke this CLI."
        )
        for i in range(2, args.max_iterations + 1):
            state = gather_repo_state(args.repo)
            priority, context = resolve_priority(state, args.repo)
            prompt = render_prompt(
                args.repo, priority, context, state,
                max_diff_chars=args.max_diff_chars,
                post_mode=args.post_mode,
            )
            out = base.with_suffix(f".{i}.md") if base.suffix else base.with_name(f"{base.name}.{i}")
            out.write_text(prompt)
            print(f"iteration {i}/{args.max_iterations} rendered to {out}")
        return 0

    if args.output:
        args.output.write_text(prompt)
        print(f"wrote {len(prompt)} chars to {args.output}", file=sys.stderr)
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
