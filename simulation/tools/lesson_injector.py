"""Prompt enhancer that prepends the most relevant lessons.

Token discipline is the whole reason this module exists. We retrieve at
most two lessons (~60 tokens each + ~30 of formatting = under 200 added
tokens), prepend them to the action prompt, and return the result. If no
lessons match, the original prompt is returned untouched so the loop pays
zero overhead in the cold-start phase.

Usage::

    from simulation.tools.lesson_injector import LessonInjector

    injector = LessonInjector()
    enhanced = injector.enhance_prompt(
        original_prompt=action_prompt,
        issue_title=issue["title"],
        issue_body=issue["body"],
    )
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

from simulation.tools.lesson_repository import LessonRepository

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 2
INJECTION_HEADER = "## Past Lessons (follow these when applicable)"


@dataclass
class InjectionResult:
    """Diagnostic record so callers can log token overhead."""

    enhanced_prompt: str
    lesson_count: int
    added_word_count: int


class LessonInjector:
    """Wrapper around :class:`LessonRepository` that produces prompt sections."""

    def __init__(
        self,
        storage_path: str | os.PathLike | None = None,
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.repository = LessonRepository(storage_path)
        self.top_k = top_k

    def _format_section(self, advice_lines: list[str]) -> str:
        bullets = "\n".join(f"- {line}" for line in advice_lines)
        return f"{INJECTION_HEADER}\n{bullets}\n\n---\n\n"

    def retrieve_lessons(self, issue_title: str, issue_body: str) -> list[str]:
        query = f"{issue_title or ''} {issue_body or ''}".strip()
        if not query:
            return []
        return self.repository.retrieve(query, top_k=self.top_k)

    def enhance_prompt(
        self,
        *,
        original_prompt: str,
        issue_title: str = "",
        issue_body: str = "",
    ) -> str:
        """Return the prompt with relevant lessons prepended (or unchanged)."""
        lessons = self.retrieve_lessons(issue_title, issue_body)
        if not lessons:
            return original_prompt
        section = self._format_section(lessons)
        return section + original_prompt

    def enhance_with_diagnostics(
        self,
        *,
        original_prompt: str,
        issue_title: str = "",
        issue_body: str = "",
    ) -> InjectionResult:
        """Same as :meth:`enhance_prompt` but report what was added."""
        lessons = self.retrieve_lessons(issue_title, issue_body)
        if not lessons:
            return InjectionResult(
                enhanced_prompt=original_prompt,
                lesson_count=0,
                added_word_count=0,
            )
        section = self._format_section(lessons)
        added_words = len(section.split())
        return InjectionResult(
            enhanced_prompt=section + original_prompt,
            lesson_count=len(lessons),
            added_word_count=added_words,
        )


__all__ = ["DEFAULT_TOP_K", "INJECTION_HEADER", "InjectionResult", "LessonInjector"]
