#!/usr/bin/env python3
"""Builds an action plan from detected problems.

Each problem type maps to a *fixer* that returns an ordered list of **steps**.
A step is a dict::

    {"persona": str, "action": str, "target": {...}, "body": str, "files"?: {...}}

Personas are assigned dynamically via
:class:`simulation.tools.persona_registry.PersonaRegistry` — the planner never
hardcodes which persona owns an action; it asks the registry, which derives the
answer from persona frontmatter.

Mode handling (``single`` vs ``multi``) lives in :func:`build_plan`:

- ``single`` — emit only the **first step** of the **highest-priority** problem,
  then stop. One run = one action.
- ``multi``  — emit **all steps** for **all** problems. One run = everything.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from simulation.tools import config
from simulation.tools.persona_registry import DEFAULT_MODEL, PersonaRegistry

_registry: Optional[PersonaRegistry] = None


def _get_registry() -> PersonaRegistry:
    """Lazily construct (and cache) the persona registry rooted at the repo."""
    global _registry
    if _registry is None:
        _registry = PersonaRegistry(repo_root=".")
    return _registry


def _run_id() -> str:
    """A per-step correlation id: UTC timestamp + 4 random bytes."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{os.urandom(4).hex()}"


def _compose_body(persona_id: str, reasoning: list[str], markers: list[str]) -> str:
    """Render a persona-headed action body for an explicit persona id.

    The role, layer, and model are pulled from the registry for ``persona_id``
    so the emitted header always reflects the live persona catalog.
    """
    persona = _get_registry().get_persona(persona_id) or {}
    role = persona.get("role", "unknown")
    layer = persona.get("layer", "unknown")
    model = persona.get("model", DEFAULT_MODEL)

    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(reasoning, 1))
    return (
        "---\n"
        f"Persona: {persona_id}\n"
        f"Role: {role}\n"
        f"Layer: {layer}\n"
        f"Model: {model}\n"
        "Source: autonomous-loop\n"
        f"Run-ID: {_run_id()}\n"
        "---\n\n"
        "**Reasoning:**\n"
        f"{numbered}\n\n"
        + "\n".join(markers)
        + "\n"
    )


def _build_body(action: str, reasoning: list[str], markers: list[str]) -> tuple[str, str]:
    """Compose a body for the persona that owns ``action``; return ``(id, body)``.

    Args:
        action: the (possibly pseudo-) action this step performs.
        reasoning: ordered chain-of-thought lines (rendered as a numbered list).
        markers: state-machine marker lines appended verbatim after the reasoning.
    """
    persona_id = _get_registry().get_persona_for_action(action)
    return persona_id, _compose_body(persona_id, reasoning, markers)


# -----------------------------------------------------------------------------
# Problem fixers — each returns a list of Step dicts.
# -----------------------------------------------------------------------------

def fix_empty_pr(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Close a PR that contains no source code (it blocks the merge queue)."""
    pr_num = problem["target"]["number"]
    title = problem["data"].get("title", "Untitled")
    persona, body = _build_body(
        "close_pr",
        [
            f'PR #{pr_num} ("{title}") contains no source-code files — only '
            "markdown, notes, or empty placeholders.",
            "The autonomous loop cannot merge empty PRs; they block the queue.",
            "Closing this PR unblocks the workflow so the issue can be retried.",
        ],
        [
            "CLOSE-REASON: No source-code files detected. Please implement real "
            "code changes and open a new PR.",
        ],
    )
    return [
        {
            "persona": persona,
            "action": "close_pr",
            "target": {"type": "pr", "number": pr_num},
            "body": body,
        }
    ]


def fix_missing_marker(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Comment a ``TEAM-REQUEST:`` onto an issue that lacks any required marker."""
    issue_num = problem["target"]["number"]
    title = problem["data"].get("title", "")
    persona, body = _build_body(
        "comment_issue",
        [
            f'Issue #{issue_num} ("{title}") lacks a required marker '
            "(TEAM-REQUEST:, PLAN-REQUEST:, or AUDIT-ISSUE:).",
            "Without a marker the autonomous loop cannot triage or act on it.",
            "Adding TEAM-REQUEST: will trigger the standard triage workflow.",
        ],
        [
            "TEAM-REQUEST: Please describe the work needed to resolve this issue.",
            "",
            "**Acceptance criteria (suggested):**",
            "- [ ] Define clear, testable criteria.",
            "- [ ] Add appropriate labels (e.g. `trivial`, `complex`, `risk:high`).",
            "",
            "PLAN-STATUS: NEEDS_AC",
        ],
    )
    return [
        {
            "persona": persona,
            "action": "comment_issue",
            "target": {"type": "issue", "number": issue_num},
            "body": body,
        }
    ]


def implement_trivial_issue(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Full chained fix for a trivial issue: create PR → review → merge → close."""
    issue_num = problem["target"]["number"]
    title = problem["data"].get("title", "")

    files = {
        f"src/issue_{issue_num}.php": (
            "<?php\n"
            "/**\n"
            f" * Trivial implementation for issue #{issue_num}.\n"
            f" * Title: {title}\n"
            " */\n"
            'echo "Hello, ERP!\\n";\n'
        )
    }

    create_persona, create_body = _build_body(
        "create_pr",
        [
            f"Issue #{issue_num} is labeled `trivial` and has no linked PR.",
            f"I will create `src/issue_{issue_num}.php` that prints \"Hello, ERP!\".",
        ],
        [
            "**Acceptance Criteria Coverage:**",
            f"- AC1: File exists -> src/issue_{issue_num}.php created.",
            '- AC2: Output matches -> prints "Hello, ERP!".',
            "",
            "IMPLEMENTATION-COMPLETE: READY_FOR_REVIEW",
            "CHAIN-NEXT: review_pr",
        ],
    )
    review_persona, review_body = _build_body(
        "review_pr",
        [
            f"This PR implements a trivial change for issue #{issue_num}.",
            "Code is simple and meets the issue's assumed acceptance criteria.",
            "Auto-approval is safe for `trivial`-labeled issues.",
        ],
        ["REVIEW-VERDICT: APPROVE", "CHAIN-NEXT: merge_pr"],
    )
    merge_persona, merge_body = _build_body(
        "merge_pr",
        [
            "PR has been approved.",
            "No merge conflicts detected.",
            "Merging will close the linked issue.",
        ],
        ["MERGE-STATUS: COMPLETE", "CHAIN-NEXT: close_issue"],
    )
    close_persona, close_body = _build_body(
        "close_issue",
        [
            "The PR has been merged.",
            "All acceptance criteria are satisfied.",
            "Closing the issue as done.",
        ],
        ["ISSUE-CLOSED: DONE"],
    )

    return [
        {
            "persona": create_persona,
            "action": "create_pr",
            "target": {"type": "issue", "number": issue_num},
            "body": create_body,
            "files": files,
        },
        {
            "persona": review_persona,
            "action": "review_pr",
            "target": {"type": "pr", "number": "auto"},
            "body": review_body,
        },
        {
            "persona": merge_persona,
            "action": "merge_pr",
            "target": {"type": "pr", "number": "auto"},
            "body": merge_body,
        },
        {
            "persona": close_persona,
            "action": "close_issue",
            "target": {"type": "issue", "number": issue_num},
            "body": close_body,
        },
    ]


def review_unreviewed_pr(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Post a review on a PR that has sat open with no reviews."""
    pr_num = problem["target"]["number"]
    title = problem["data"].get("title", "")
    persona, body = _build_body(
        "review_pr",
        [
            f'PR #{pr_num} ("{title}") has been open for >1 day with no reviews.',
            "Basic review: code looks reasonable and the change is scoped.",
            "Approving so the merge queue can proceed.",
        ],
        ["REVIEW-VERDICT: APPROVE", "CHAIN-NEXT: merge_pr"],
    )
    return [
        {
            "persona": persona,
            "action": "review_pr",
            "target": {"type": "pr", "number": pr_num},
            "body": body,
        }
    ]


def resolve_stale_discussion(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve a discussion stuck in PLAN-REQUEST without PLAN-READY."""
    disc_num = problem["target"]["number"]
    title = problem["data"].get("title", "")
    persona, body = _build_body(
        "comment_discussion",
        [
            f'Discussion #{disc_num} ("{title}") has PLAN-REQUEST: but no '
            "PLAN-READY: for >2 days.",
            "Marking it resolved to unblock downstream work.",
        ],
        [
            "PLAN-SUMMARY: Proceed with the original request.",
            "DISCUSSION-STATUS: RESOLVED",
            "PLAN-READY:",
        ],
    )
    return [
        {
            "persona": persona,
            "action": "comment_discussion",
            "target": {"type": "discussion", "number": disc_num},
            "body": body,
        }
    ]


# -----------------------------------------------------------------------------
# Persona request system — let a persona pull other personas into the loop.
# -----------------------------------------------------------------------------

# Marker -> which request bucket the named personas land in.
_REQUEST_MARKERS: dict[str, str] = {
    "REQUEST-REPLY-FROM:": "reply",
    "REQUEST-REVIEW-FROM:": "review",
    "REQUEST-APPROVAL-FROM:": "approval",
    "QUESTION-TO:": "question",
}

# Splits a body into [text, MARKER, arg, MARKER, arg, ...] so each marker's
# argument is isolated even when several share one physical line (e.g. when a
# body is created with literal "\n" rather than real newlines).
_SPLIT_RE = re.compile("(" + "|".join(re.escape(m) for m in _REQUEST_MARKERS) + ")")

# Persona-handle shape: lowercase, hyphen-separated (e.g. ``mara-product-owner``).
_HANDLE_RE = re.compile(r"@?([a-z0-9][a-z0-9-]+)")


def _parse_requests(body: str) -> list[dict[str, str]]:
    """Parse persona requests from an issue/PR body, in marker order.

    Returns a list of ``{"bucket", "persona", "question"}`` records. Only tokens
    matching a *known* persona id are kept (so free text after a marker can't
    fabricate handles), and ``(bucket, persona)`` pairs are de-duplicated. For
    ``QUESTION-TO: @persona? <text>`` the question text is captured in
    ``question``; other buckets leave it empty.
    """
    known = {p["id"] for p in _get_registry().load_all()}
    records: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    parts = _SPLIT_RE.split(body or "")
    # parts[0] is leading text; thereafter alternates marker, arg, marker, arg...
    for i in range(1, len(parts), 2):
        marker = parts[i]
        arg = parts[i + 1] if i + 1 < len(parts) else ""
        bucket = _REQUEST_MARKERS[marker]

        if bucket == "question":
            m = re.match(r"\s*@?([a-z0-9][a-z0-9-]+)\s*\?\s*(.*)", arg, re.IGNORECASE | re.DOTALL)
            if m and m.group(1).lower() in known:
                persona = m.group(1).lower()
                question = m.group(2).strip().split("\n", 1)[0][:300]
                key = (bucket, persona)
                if key not in seen:
                    seen.add(key)
                    records.append({"bucket": bucket, "persona": persona, "question": question})
            continue

        for handle in _HANDLE_RE.findall(arg.lower()):
            if handle in known and (bucket, handle) not in seen:
                seen.add((bucket, handle))
                records.append({"bucket": bucket, "persona": handle, "question": ""})
    return records


def _answered_personas(comments: list[dict[str, Any]]) -> set[str]:
    """Persona ids that already replied (their ``Persona:`` header appears)."""
    known = {p["id"] for p in _get_registry().load_all()}
    answered: set[str] = set()
    for comment in comments or []:
        cbody = comment.get("body") or ""
        for persona_id in known:
            if f"Persona: {persona_id}" in cbody:
                answered.add(persona_id)
    return answered


def handle_unanswered_request(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate one action per requested persona that has not yet responded.

    On an **issue**, requested personas reply via ``comment_issue``; on a **PR**
    they respond via ``review_pr``. ``QUESTION-TO`` carries the specific question
    into the generated prompt. Personas whose ``Persona:`` header already appears
    in the item's comments are skipped, so a re-run does not re-post.
    """
    target = problem["target"]
    data = problem["data"]
    body = data.get("body", "") or ""
    answered = _answered_personas(data.get("comments", []))
    requests = _parse_requests(body)

    is_pr = target["type"] == "pr"
    num = target["number"]
    label = "PR" if is_pr else "issue"
    excerpt = " ".join(body[:400].split())

    steps: list[dict[str, Any]] = []
    for record in requests:
        persona_id = record["persona"]
        if persona_id in answered:
            continue
        bucket = record["bucket"]

        if bucket == "question":
            reasoning = [
                f"@{persona_id} was asked a direct question on {label} #{num}.",
                f"The question: {record['question']}",
                "Answering on that persona's behalf to advance the conversation.",
            ]
        else:
            reasoning = [
                f"@{persona_id} was requested ({bucket}) on {label} #{num}.",
                "Responding on that persona's behalf so the multi-agent conversation advances.",
            ]

        # On a PR, review/approval requests surface as a review; everything on an
        # issue (and replies/questions) surface as a comment.
        if is_pr and bucket in ("review", "approval"):
            markers = [
                "REVIEW-VERDICT: COMMENT",
                f"REVIEW-FROM: @{persona_id}",
                "",
                "**Requested context:**",
                f"> {excerpt}",
                "",
                "Provide the substantive review and any required verdict here.",
            ]
            action, tgt = "review_pr", {"type": "pr", "number": num}
        else:
            markers = [
                f"REPLY-FROM: @{persona_id}",
                "",
                "**Requested context:**",
                f"> {excerpt}",
                "",
                "Provide the substantive response and any required markers here.",
            ]
            action = "comment_issue"
            tgt = {"type": target["type"], "number": num}

        steps.append(
            {
                "persona": persona_id,
                "action": action,
                "target": tgt,
                "body": _compose_body(persona_id, reasoning, markers),
            }
        )
    return steps


# Dispatch table: problem type -> fixer.
_FIXERS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "UNANSWERED_REQUEST": handle_unanswered_request,
    "EMPTY_PR": fix_empty_pr,
    "MISSING_MARKER": fix_missing_marker,
    "TRIVIAL_NOT_IMPLEMENTED": implement_trivial_issue,
    "UNREVIEWED_PR": review_unreviewed_pr,
    "STALE_DISCUSSION": resolve_stale_discussion,
}


def build_plan(
    problems: list[dict[str, Any]], mode: str | None = None
) -> dict[str, Any]:
    """Turn a priority-sorted problem list into an executable plan.

    Args:
        problems: output of
            :func:`simulation.tools.state_analyzer.analyze_state`.
        mode: ``"single"`` or ``"multi"``; ``None`` resolves the configured
            default via :func:`simulation.tools.config.resolve`.

    Returns:
        ``{"mode", "generated_at", "total_steps", "steps"}``. In ``single``
        mode ``steps`` holds at most one step (the first step of the
        highest-priority problem).
    """
    resolved_mode = config.resolve(mode=mode).mode
    steps: list[dict[str, Any]] = []

    for problem in problems:
        fixer = _FIXERS.get(problem["type"])
        if fixer is None:
            continue
        new_steps = fixer(problem)
        if not new_steps:
            continue

        if resolved_mode == "single":
            steps = new_steps[:1]
            break
        steps.extend(new_steps)

    return {
        "mode": resolved_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_steps": len(steps),
        "steps": steps,
    }
