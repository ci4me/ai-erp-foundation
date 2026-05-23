"""Tests for the self-learning lesson system.

Covers the three contracts called out in the spec:

1. Storage + retrieval round-trips a stored lesson.
2. Injection adds fewer than 200 tokens (overhead budget).
3. Retrospective extraction stores at least one lesson when the LLM
   returns a well-formed JSON array.

Plus pruning + skip-on-timeout coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

from simulation.tools import lesson_injector, lesson_repository, prune_lessons, retrospective


def _seed(repo: lesson_repository.LessonRepository, **overrides) -> lesson_repository.Lesson:
    payload = {
        "id": overrides.get("id", "test-lesson"),
        "triggers": overrides.get("triggers", ["database", "migration"]),
        "advice": overrides.get("advice", "Always backup before migration."),
        "confidence": overrides.get("confidence", 0.9),
        "usage_count": overrides.get("usage_count", 0),
        "last_used": overrides.get("last_used"),
        "issue_id": overrides.get("issue_id", 1),
        "success": overrides.get("success", True),
    }
    return repo.store(payload)


def test_lesson_storage_and_retrieval(tmp_path: Path) -> None:
    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    _seed(repo)
    retrieved = repo.retrieve("migration error in the auth module", top_k=1)
    assert len(retrieved) == 1
    assert "backup" in retrieved[0]


def test_retrieval_uses_confidence_and_recency(tmp_path: Path) -> None:
    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    _seed(repo, id="a", triggers=["auth", "token"], advice="A", confidence=0.5)
    _seed(repo, id="b", triggers=["auth", "token"], advice="B", confidence=0.9)
    out = repo.retrieve("auth token expiry", top_k=1)
    # Higher confidence wins the tie on overlap count.
    assert out == ["B"]


def test_retrieval_skips_irrelevant_lessons(tmp_path: Path) -> None:
    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    _seed(repo, triggers=["postgres", "schema"])
    assert repo.retrieve("frontend layout bug") == []


def test_injection_token_overhead(tmp_path: Path) -> None:
    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    _seed(repo)
    injector = lesson_injector.LessonInjector(storage_path=tmp_path)
    original = "This is a standard prompt for implementing a database migration."
    result = injector.enhance_with_diagnostics(
        original_prompt=original,
        issue_title="Fix database migration",
        issue_body="Need to add a new column",
    )
    assert result.lesson_count == 1
    assert result.added_word_count < 200
    assert "backup" in result.enhanced_prompt
    assert original in result.enhanced_prompt


def test_injection_returns_unchanged_when_no_match(tmp_path: Path) -> None:
    injector = lesson_injector.LessonInjector(storage_path=tmp_path)
    original = "fresh prompt with no prior art"
    enhanced = injector.enhance_prompt(
        original_prompt=original,
        issue_title="new feature",
        issue_body="something never seen before",
    )
    assert enhanced == original


def test_retrospective_extracts_lessons_from_mock_llm(tmp_path: Path) -> None:
    fake_response = json.dumps(
        [
            {
                "triggers": ["jwt", "auth"],
                "advice": "Always check existing auth middleware before adding one.",
            }
        ]
    )

    def mock_llm(prompt: str) -> str:
        assert "retrospective" in prompt.lower()
        return fake_response

    retro = retrospective.Retrospective(llm_client=mock_llm, storage_path=tmp_path)
    stored = retro.process_closed_issue(
        issue_id=999,
        title="Refactor JWT validation",
        body="We had to add a new middleware that duplicated work.",
        events=["IMPLEMENTATION-COMPLETE: TRUE", "MERGE-STATUS: COMPLETE"],
        success=True,
        close_reason="DONE",
    )
    assert len(stored) == 1
    assert "auth" in stored[0].triggers


def test_retrospective_skips_timeout_closures(tmp_path: Path) -> None:
    def fail_llm(prompt: str) -> str:  # pragma: no cover - should never run
        raise AssertionError("LLM should not be called for skipped reasons")

    retro = retrospective.Retrospective(llm_client=fail_llm, storage_path=tmp_path)
    stored = retro.process_closed_issue(
        issue_id=42,
        success=False,
        close_reason="TIMEOUT",
    )
    assert stored == []


def test_pruning_deletes_low_confidence_unused(tmp_path: Path) -> None:
    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    _seed(repo, id="keep", confidence=0.6, usage_count=2)
    _seed(repo, id="drop", confidence=0.1, usage_count=0)
    summary = prune_lessons.prune(repo)
    assert summary.deleted_low_confidence == 1
    ids = {lesson.id for lesson in repo._load_all()}
    assert ids == {"keep"}


def test_pruning_caps_at_hard_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lesson_repository, "LESSON_HARD_CAP", 3, raising=False)
    monkeypatch.setattr(prune_lessons, "LESSON_HARD_CAP", 3, raising=False)
    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    for i in range(5):
        _seed(repo, id=f"l{i}", usage_count=i, confidence=0.5)
    summary = prune_lessons.prune(repo)
    assert summary.deleted_overflow >= 2
    assert len(repo._load_all()) == 3
