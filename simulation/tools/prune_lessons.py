"""Weekly maintenance for the lesson store.

Three rules, applied in order:

1. Delete any lesson with ``confidence < LOW_CONFIDENCE_FLOOR`` *and*
   ``usage_count == 0`` — never used and the model's confidence has
   decayed below the floor.
2. For lessons with ``usage_count > 0`` whose ``last_used`` is older than
   ``DECAY_AFTER_DAYS``, multiply confidence by ``DECAY_FACTOR``.
3. If the total count still exceeds :data:`LESSON_HARD_CAP`, delete the
   least-used lessons until the cap is satisfied.

Run from cron or a GitHub Action:

    python3 -m simulation.tools.prune_lessons --storage .lessons
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from dataclasses import dataclass

from simulation.tools.lesson_repository import (
    LESSON_HARD_CAP,
    LOW_CONFIDENCE_FLOOR,
    Lesson,
    LessonRepository,
)

logger = logging.getLogger(__name__)

DECAY_AFTER_DAYS = 30
DECAY_FACTOR = 0.95


@dataclass
class PruneSummary:
    examined: int
    deleted_low_confidence: int
    decayed: int
    deleted_overflow: int


def _is_stale(last_used: str | None, *, days: int) -> bool:
    if not last_used:
        return True
    try:
        ts = _dt.datetime.fromisoformat(last_used.rstrip("Z")).replace(tzinfo=_dt.UTC)
    except ValueError:
        return True
    return (_dt.datetime.now(tz=_dt.UTC) - ts).days >= days


def prune(repository: LessonRepository) -> PruneSummary:
    lessons = repository._load_all()
    summary = PruneSummary(
        examined=len(lessons),
        deleted_low_confidence=0,
        decayed=0,
        deleted_overflow=0,
    )

    survivors: list[Lesson] = []
    for lesson in lessons:
        if lesson.confidence < LOW_CONFIDENCE_FLOOR and lesson.usage_count == 0:
            repository.delete(lesson.id)
            summary.deleted_low_confidence += 1
            continue
        if lesson.usage_count > 0 and _is_stale(lesson.last_used, days=DECAY_AFTER_DAYS):
            lesson.confidence = max(0.0, lesson.confidence * DECAY_FACTOR)
            repository.update(lesson)
            summary.decayed += 1
        survivors.append(lesson)

    if len(survivors) > LESSON_HARD_CAP:
        # Drop the least-used lessons first (ties broken by lowest confidence).
        survivors.sort(key=lambda l: (l.usage_count, l.confidence))
        overflow = len(survivors) - LESSON_HARD_CAP
        for lesson in survivors[:overflow]:
            repository.delete(lesson.id)
            summary.deleted_overflow += 1

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage", default=None, help="lesson storage path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    repository = LessonRepository(args.storage)
    summary = prune(repository)
    print(
        f"examined={summary.examined} "
        f"deleted_low_confidence={summary.deleted_low_confidence} "
        f"decayed={summary.decayed} "
        f"deleted_overflow={summary.deleted_overflow}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))


__all__ = ["DECAY_AFTER_DAYS", "DECAY_FACTOR", "PruneSummary", "prune"]
