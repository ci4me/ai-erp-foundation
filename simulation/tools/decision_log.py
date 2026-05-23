"""Decision log stored as an HTML comment at the bottom of an issue body.

The autonomous loop produces many sequential decisions: database choice,
framework selection, scope boundaries. Without a persistent record, later
agents re-litigate decided questions and waste tokens. We piggyback on the
issue body — a place every agent reads anyway — by storing an HTML comment
the loop owns:

    <!-- DECISIONS: database=mysql; frontend=react -->

Format
------

- Wrapped in ``<!-- DECISIONS: ... -->`` on its own line.
- Key=value pairs separated by ``;``.
- Keys are normalized to lowercase. Values keep original casing.
- A reopen request is a key prefixed by ``reopen:`` (e.g. ``reopen:database``).
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Mapping

DECISION_BLOCK_RE = re.compile(
    r"<!--\s*DECISIONS:\s*(.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
COT_BLOCK_RE = re.compile(
    r"<!--\s*COT:(?P<ts>[\dTZ:.+-]+)\|agent=(?P<agent>[^|]+)\|steps=(?P<steps>\d+)\|content=(?P<content>.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
MAX_STORED_COT_ENTRIES = 5


@dataclass
class DecisionLog:
    """Parsed decision-log block + helpers to mutate and re-render it."""

    decisions: dict[str, str]

    def get(self, key: str) -> str | None:
        return self.decisions.get(key.lower())

    def set(self, key: str, value: str) -> None:
        self.decisions[key.lower()] = value

    def reopen(self, key: str) -> None:
        """Remove a previously decided key so it can be re-decided."""
        self.decisions.pop(key.lower(), None)

    def conflicts_with(self, new_decisions: Mapping[str, str]) -> dict[str, tuple[str, str]]:
        """Return ``{key: (existing, proposed)}`` for any contradicting pair."""
        out: dict[str, tuple[str, str]] = {}
        for key, value in new_decisions.items():
            existing = self.decisions.get(key.lower())
            if existing is not None and existing != value:
                out[key.lower()] = (existing, value)
        return out

    def render(self) -> str:
        """Render the decisions back to the canonical HTML comment block."""
        if not self.decisions:
            return ""
        parts = "; ".join(f"{k}={v}" for k, v in sorted(self.decisions.items()))
        return f"<!-- DECISIONS: {parts} -->"


def parse_issue_body(body: str) -> DecisionLog:
    """Extract the decision log from an issue body. Missing → empty log."""
    if not body:
        return DecisionLog(decisions={})
    match = DECISION_BLOCK_RE.search(body)
    if not match:
        return DecisionLog(decisions={})
    decisions: dict[str, str] = {}
    payload = match.group(1).strip()
    for pair in re.split(r"[;,\n]+", payload):
        if not pair.strip() or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        decisions[key.strip().lower()] = value.strip()
    return DecisionLog(decisions=decisions)


def write_to_body(body: str, log: DecisionLog) -> str:
    """Insert or replace the decision-log block at the end of an issue body."""
    rendered = log.render()
    if DECISION_BLOCK_RE.search(body or ""):
        return DECISION_BLOCK_RE.sub(rendered, body or "")
    if not rendered:
        return body or ""
    body = (body or "").rstrip()
    return f"{body}\n\n{rendered}\n" if body else f"{rendered}\n"


@dataclass
class CotEntry:
    """One Chain-of-Thought block appended to the issue body."""

    timestamp: str
    agent: str
    steps: int
    content: str

    def render(self) -> str:
        safe_content = self.content.replace("-->", "→")
        return (
            f"<!-- COT:{self.timestamp}|agent={self.agent}|steps={self.steps}"
            f"|content={safe_content} -->"
        )


def parse_cot_entries(body: str) -> list[CotEntry]:
    """Return all stored CoT entries from an issue body, oldest first."""
    entries: list[CotEntry] = []
    for match in COT_BLOCK_RE.finditer(body or ""):
        entries.append(
            CotEntry(
                timestamp=match.group("ts").strip(),
                agent=match.group("agent").strip(),
                steps=int(match.group("steps")),
                content=match.group("content").strip(),
            )
        )
    return entries


def append_cot(body: str, entry: CotEntry, *, max_entries: int = MAX_STORED_COT_ENTRIES) -> str:
    """Append a CoT entry to the issue body, capped at the most recent ``max_entries``."""
    existing = parse_cot_entries(body or "")
    existing.append(entry)
    if len(existing) > max_entries:
        existing = existing[-max_entries:]
    # Strip prior CoT blocks then re-append the trimmed set.
    stripped = COT_BLOCK_RE.sub("", body or "").rstrip()
    rendered = "\n".join(e.render() for e in existing)
    return f"{stripped}\n\n{rendered}\n" if stripped else f"{rendered}\n"


def latest_cot(body: str) -> CotEntry | None:
    entries = parse_cot_entries(body or "")
    return entries[-1] if entries else None


DECISION_LOG_PROMPT_NOTE = (
    "Before replying, read the decision log embedded in the issue body "
    "(`<!-- DECISIONS: ... -->`). Never contradict a previously accepted "
    "decision unless you first emit a `REOPEN-DECISION: <key>` request."
)


__all__ = [
    "COT_BLOCK_RE",
    "CotEntry",
    "DECISION_LOG_PROMPT_NOTE",
    "DecisionLog",
    "MAX_STORED_COT_ENTRIES",
    "append_cot",
    "latest_cot",
    "parse_cot_entries",
    "parse_issue_body",
    "write_to_body",
]
