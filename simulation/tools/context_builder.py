"""Conversation context trimming used by the autonomous-loop prompt renderer.

The legacy renderer in :mod:`simulation.tools.next_prompt_legacy` builds a
prompt by concatenating the issue body, every comment, and the persona
catalog. A 17-comment thread plus the catalog easily reaches 5–6 K tokens
of input. Most of that history is redundant for the next action: only the
last few markers (state transitions) and the last few human messages
matter.

:func:`truncate_conversation` returns a trimmed comment list plus a
length-capped body. The output is fed back into the prompt template so
the LLM call shrinks proportionally — typical savings: ~2000 → ~400
tokens per prompt.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

DEFAULT_MAX_MARKERS = 5
DEFAULT_MAX_HUMAN = 3
DEFAULT_MAX_BODY_CHARS = 500
_MARKER_RE = re.compile(r"^[A-Z][A-Z0-9_-]+:\s*\S", re.MULTILINE)


def _is_marker_bearing(body: str) -> bool:
    return bool(_MARKER_RE.search(body or ""))


def _is_human(comment: dict[str, Any]) -> bool:
    """Heuristic: bots either declare ``type: Bot`` or open with a YAML header."""
    author = comment.get("author") or {}
    if isinstance(author, dict):
        if author.get("type") and author["type"] != "User":
            return False
    body = comment.get("body") or ""
    if body.startswith("---") and "Persona:" in body[:200]:
        return False
    return True


def truncate_conversation(
    comments: Iterable[dict[str, Any]],
    issue_body: str,
    *,
    max_markers: int = DEFAULT_MAX_MARKERS,
    max_human: int = DEFAULT_MAX_HUMAN,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> tuple[list[dict[str, Any]], str]:
    """Trim ``comments`` to the last marker-bearing + last human entries.

    Returns ``(trimmed_comments, trimmed_body)``. The body is hard-capped
    at ``max_body_chars`` characters so a long issue description does not
    swamp the prompt; the trimmed comments preserve original ``createdAt``
    ordering when present.
    """
    items = list(comments or [])
    markers = [c for c in items if _is_marker_bearing(c.get("body") or "")]
    humans = [c for c in items if _is_human(c) and not _is_marker_bearing(c.get("body") or "")]
    kept = markers[-max_markers:] + humans[-max_human:]
    kept.sort(key=lambda c: c.get("createdAt") or c.get("created_at") or "")
    body = (issue_body or "")
    trimmed_body = body if len(body) <= max_body_chars else body[: max_body_chars - 1] + "…"
    return kept, trimmed_body


def estimate_token_savings(
    full_comments: Iterable[dict[str, Any]],
    full_body: str,
    trimmed_comments: Iterable[dict[str, Any]],
    trimmed_body: str,
) -> int:
    """Return the rough word-count reduction (a proxy for token savings)."""
    def words(*parts: str) -> int:
        return sum(len((p or "").split()) for p in parts)

    full = words(full_body, *(c.get("body") or "" for c in full_comments))
    trimmed = words(trimmed_body, *(c.get("body") or "" for c in trimmed_comments))
    return max(full - trimmed, 0)


__all__ = [
    "DEFAULT_MAX_BODY_CHARS",
    "DEFAULT_MAX_HUMAN",
    "DEFAULT_MAX_MARKERS",
    "estimate_token_savings",
    "truncate_conversation",
]
