"""Storage and retrieval for the self-learning lesson system.

A "lesson" is a tiny advice card — a few trigger keywords and a single
sentence — that the autonomous loop earned by closing an issue. Lessons live
on disk as one JSON file per lesson under ``LESSONS_PATH`` (default
``.lessons/`` at the repo root). The on-disk schema is intentionally flat
so we don't need a database:

.. code-block:: json

    {
      "id": "issue_123_abc456",
      "issue_id": 123,
      "created_at": "2025-02-20T10:00:00Z",
      "success": true,
      "triggers": ["jwt", "authentication", "middleware"],
      "advice": "Always check existing auth middleware before creating a new one.",
      "confidence": 0.9,
      "usage_count": 0,
      "last_used": null
    }

Retrieval is a deliberate keyword-overlap scoring rather than an embedding
search: with fewer than ~1000 lessons the linear scan is negligible and we
get full determinism, zero infra, and no model dependency.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LESSONS_DIR = REPO_ROOT / ".lessons"
MAX_TRIGGERS = 5
MAX_ADVICE_CHARS = 120
INITIAL_CONFIDENCE = 0.9
LOW_CONFIDENCE_FLOOR = 0.3
LESSON_HARD_CAP = 200

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


@dataclass
class Lesson:
    """One stored lesson card."""

    id: str
    triggers: list[str]
    advice: str
    confidence: float = INITIAL_CONFIDENCE
    usage_count: int = 0
    last_used: str | None = None
    issue_id: int | None = None
    created_at: str | None = None
    success: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Lesson":
        clean = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**clean)


def _resolve_storage_path(override: str | os.PathLike | None) -> Path:
    """Pick the storage directory; env var wins over the default."""
    if override is not None:
        return Path(override)
    env = os.environ.get("LESSONS_PATH")
    return Path(env) if env else DEFAULT_LESSONS_DIR


def _normalize_triggers(raw: Iterable[str]) -> list[str]:
    """Lowercase, dedup, cap at :data:`MAX_TRIGGERS`."""
    seen: list[str] = []
    for item in raw or []:
        token = str(item).strip().lower()
        if not token:
            continue
        if token not in seen:
            seen.append(token)
        if len(seen) >= MAX_TRIGGERS:
            break
    return seen


def _trim_advice(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_ADVICE_CHARS:
        return text
    return text[: MAX_ADVICE_CHARS - 1].rstrip() + "…"


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class LessonRepository:
    """File-backed lesson store with keyword-overlap retrieval.

    The repository is safe to construct even when the storage directory does
    not exist or is read-only: ``store()`` and pruning emit a warning and
    return ``None`` rather than crash, so the autonomous loop never breaks
    just because a learning sidecar failed.
    """

    def __init__(self, storage_path: str | os.PathLike | None = None) -> None:
        self.storage_path = _resolve_storage_path(storage_path)
        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            self._writable = os.access(self.storage_path, os.W_OK)
        except OSError as exc:
            logger.warning("lesson storage path unavailable: %s", exc)
            self._writable = False

    # -- writes --------------------------------------------------------

    def store(self, lesson: dict | Lesson) -> Lesson | None:
        """Persist one lesson; returns the stored Lesson or None on failure."""
        if not self._writable:
            logger.warning("lesson storage read-only, skipping store")
            return None
        if isinstance(lesson, dict):
            normalized = Lesson(
                id=lesson.get("id") or f"lesson_{uuid.uuid4().hex[:8]}",
                triggers=_normalize_triggers(lesson.get("triggers") or []),
                advice=_trim_advice(lesson.get("advice") or ""),
                confidence=float(lesson.get("confidence", INITIAL_CONFIDENCE)),
                usage_count=int(lesson.get("usage_count", 0)),
                last_used=lesson.get("last_used"),
                issue_id=lesson.get("issue_id"),
                created_at=lesson.get("created_at") or _now_iso(),
                success=bool(lesson.get("success", True)),
            )
        else:
            normalized = lesson
            normalized.triggers = _normalize_triggers(normalized.triggers)
            normalized.advice = _trim_advice(normalized.advice)
            normalized.created_at = normalized.created_at or _now_iso()
        if not normalized.triggers or not normalized.advice:
            logger.warning("lesson missing triggers or advice; skipping")
            return None
        path = self.storage_path / f"{normalized.id}.json"
        try:
            path.write_text(json.dumps(normalized.to_dict(), indent=2, sort_keys=True))
        except OSError as exc:
            logger.warning("could not write lesson %s: %s", normalized.id, exc)
            return None
        return normalized

    def update(self, lesson: Lesson) -> None:
        if not self._writable:
            return
        path = self.storage_path / f"{lesson.id}.json"
        try:
            path.write_text(json.dumps(lesson.to_dict(), indent=2, sort_keys=True))
        except OSError as exc:
            logger.warning("could not update lesson %s: %s", lesson.id, exc)

    def delete(self, lesson_id: str) -> None:
        path = self.storage_path / f"{lesson_id}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("could not delete lesson %s: %s", lesson_id, exc)

    # -- reads ---------------------------------------------------------

    def _load_all(self) -> list[Lesson]:
        if not self.storage_path.exists():
            return []
        lessons: list[Lesson] = []
        for path in sorted(self.storage_path.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("skipping malformed lesson %s: %s", path.name, exc)
                continue
            try:
                lessons.append(Lesson.from_dict(data))
            except TypeError as exc:
                logger.warning("skipping lesson with wrong shape %s: %s", path.name, exc)
        return lessons

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        """Return up to ``top_k`` advice strings ranked by trigger overlap.

        Ties on overlap break on confidence (high first); double ties on
        ``last_used`` recency (recent first). When no lesson matches at
        all, an empty list is returned — the caller should leave the
        original prompt untouched.
        """
        if not query:
            return []
        query_tokens = set(_TOKEN_RE.findall(query.lower()))
        scored: list[tuple[int, float, str, Lesson]] = []
        for lesson in self._load_all():
            score = sum(1 for trigger in lesson.triggers if trigger in query_tokens)
            if score == 0:
                continue
            recency = lesson.last_used or lesson.created_at or ""
            scored.append((score, lesson.confidence, recency, lesson))
        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        winners = [lesson for *_, lesson in scored[:top_k]]
        # Side-effect: bump usage counters so confidence pruning stays honest.
        for lesson in winners:
            lesson.usage_count += 1
            lesson.last_used = _now_iso()
            self.update(lesson)
        return [lesson.advice for lesson in winners]


__all__ = [
    "DEFAULT_LESSONS_DIR",
    "INITIAL_CONFIDENCE",
    "LESSON_HARD_CAP",
    "LOW_CONFIDENCE_FLOOR",
    "Lesson",
    "LessonRepository",
    "MAX_ADVICE_CHARS",
    "MAX_TRIGGERS",
]
