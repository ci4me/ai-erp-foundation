"""Lesson extraction from closed issues.

The retrospective runs once per closed issue (not per action) and asks the
shared LLM client to distill at most two concrete, transferable lessons
from the issue's conversation. The output is stored via
:class:`LessonRepository` so future iterations can retrieve it.

We deliberately skip closures whose terminal marker is ``TIMEOUT`` or
``UNRESOLVED`` / ``INACTIVE``: lessons from those tend to be "we gave up"
which is not useful as guidance.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from simulation.tools.lesson_repository import (
    INITIAL_CONFIDENCE,
    Lesson,
    LessonRepository,
    MAX_ADVICE_CHARS,
    MAX_TRIGGERS,
    _normalize_triggers,
    _now_iso,
    _trim_advice,
)

logger = logging.getLogger(__name__)

SKIP_CLOSE_REASONS = frozenset({"TIMEOUT", "UNRESOLVED", "INACTIVE"})
LESSON_PROMPT = """\
You are a retrospective analyst. The following issue is now closed (success: {success}).

Issue title: {title}
Issue body summary: {body}
Key events (markers and outcomes): {events}

Extract up to 2 concrete, actionable lessons. Each lesson must have:
- triggers: 2-4 keywords that would trigger this lesson in future issues (lowercase).
- advice: one sentence (max 120 chars) of what to do or avoid.

Return JSON array:
[{{"triggers": ["kw1","kw2"], "advice": "..."}}]
"""


LlmClient = Callable[[str], str]


@dataclass
class Retrospective:
    """One-shot lesson extractor wired to a chat-completion client."""

    llm_client: LlmClient
    storage_path: str | os.PathLike | None = None

    def __post_init__(self) -> None:
        self.repository = LessonRepository(self.storage_path)

    def _should_skip(self, close_reason: str | None) -> bool:
        if not close_reason:
            return False
        return close_reason.strip().upper() in SKIP_CLOSE_REASONS

    def _build_prompt(
        self,
        *,
        title: str,
        body: str,
        events: list[str],
        success: bool,
    ) -> str:
        events_blob = "\n".join(f"- {event}" for event in events[:20]) or "(no markers)"
        return LESSON_PROMPT.format(
            success=str(success).lower(),
            title=title.strip()[:120],
            body=(body or "").strip()[:500],
            events=events_blob,
        )

    def _parse_lessons(self, raw: str) -> list[dict]:
        """Parse the LLM response into a list of lesson dicts; tolerate junk."""
        if not raw:
            return []
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        payload = match.group(0) if match else raw
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("retrospective output not valid JSON; skipping")
            return []
        if not isinstance(data, list):
            return []
        cleaned: list[dict] = []
        for item in data[:2]:
            if not isinstance(item, dict):
                continue
            triggers = _normalize_triggers(item.get("triggers") or [])
            advice = _trim_advice(item.get("advice") or "")
            if len(triggers) < 2 or not advice:
                continue
            cleaned.append({"triggers": triggers, "advice": advice})
        return cleaned

    def process_closed_issue(
        self,
        *,
        issue_id: int,
        title: str = "",
        body: str = "",
        events: list[str] | None = None,
        success: bool = True,
        close_reason: str | None = None,
        conversation_log: list[str] | None = None,
    ) -> list[Lesson]:
        """Extract lessons from a closed issue and persist them.

        ``conversation_log`` is kept as a convenience for callers that want
        to pass the raw stream of comments; it is folded into ``events``
        when ``events`` is not provided.
        """
        if self._should_skip(close_reason):
            logger.info("skipping retrospective for issue %s (reason=%s)", issue_id, close_reason)
            return []
        events = list(events or conversation_log or [])
        prompt = self._build_prompt(title=title, body=body, events=events, success=success)
        try:
            raw = self.llm_client(prompt)
        except Exception as exc:  # noqa: BLE001 — never break the loop
            logger.warning("retrospective LLM call failed: %s", exc)
            return []
        stored: list[Lesson] = []
        for entry in self._parse_lessons(raw):
            payload = {
                "id": f"issue_{issue_id}_{uuid.uuid4().hex[:6]}",
                "issue_id": issue_id,
                "created_at": _now_iso(),
                "success": success,
                "triggers": entry["triggers"],
                "advice": entry["advice"],
                "confidence": INITIAL_CONFIDENCE,
                "usage_count": 0,
                "last_used": None,
            }
            saved = self.repository.store(payload)
            if saved is not None:
                stored.append(saved)
        return stored


__all__ = ["LESSON_PROMPT", "Retrospective", "SKIP_CLOSE_REASONS"]
