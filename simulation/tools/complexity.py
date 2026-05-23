"""Task-complexity classifier for the Chain-of-Thought (CoT) system.

The autonomous loop asks every agent to produce a numbered ``**Reasoning:**``
section before its final output. Demanding the same length of reasoning for
"fix a typo" and "design an event-sourced billing system" wastes tokens and
slows the loop down. This classifier picks a CoT length that matches the
task:

- *trivial* (label ``trivial``, or override ``cot-short``): 2 steps × 5 words
- *medium* (default): 3 steps × 8 words
- *complex* (label ``complex`` or keywords like ``architecture``, ``database``,
  ``api``, ``security``): 5 steps × 12 words

The classifier is pure: it takes the issue body and labels and returns a
lightweight dictionary the validator/template renderer can consume.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

COMPLEX_KEYWORDS = (
    "architecture",
    "database",
    "api",
    "security",
    "auth",
    "migration",
    "schema",
    "distributed",
    "event sourcing",
    "concurrency",
    "encryption",
)
COMPLEX_LABELS = frozenset({"complex", "risk:high", "risk:critical", "area:agent-governance"})
TRIVIAL_LABELS = frozenset({"trivial", "quick-fix", "typo"})
COT_SHORT_OVERRIDE = "cot-short"
COT_FULL_OVERRIDE = "cot-full"


@dataclass(frozen=True)
class Complexity:
    """Resolved CoT requirements for a task."""

    level: str
    min_steps: int
    min_words_per_step: int

    def as_dict(self) -> dict[str, int | str]:
        return asdict(self)


_LEVELS = {
    "trivial": Complexity("trivial", 2, 5),
    "medium": Complexity("medium", 3, 8),
    "complex": Complexity("complex", 5, 12),
}


def detect_complexity(issue_body: str, labels: list[str] | tuple[str, ...]) -> dict:
    """Pick the CoT requirement for an issue.

    Override precedence (highest wins):

    1. ``cot-short`` label → trivial.
    2. ``cot-full`` label → complex.
    3. ``trivial``/``quick-fix``/``typo`` label → trivial.
    4. ``complex``/``risk:high``/``risk:critical`` label → complex.
    5. body contains a complex keyword → complex.
    6. default → medium.
    """
    label_set = {label.lower() for label in labels or ()}
    if COT_SHORT_OVERRIDE in label_set:
        return _LEVELS["trivial"].as_dict()
    if COT_FULL_OVERRIDE in label_set:
        return _LEVELS["complex"].as_dict()
    if label_set & TRIVIAL_LABELS:
        return _LEVELS["trivial"].as_dict()
    if label_set & COMPLEX_LABELS:
        return _LEVELS["complex"].as_dict()
    lowered = (issue_body or "").lower()
    if any(keyword in lowered for keyword in COMPLEX_KEYWORDS):
        return _LEVELS["complex"].as_dict()
    return _LEVELS["medium"].as_dict()


__all__ = ["COMPLEX_KEYWORDS", "Complexity", "detect_complexity"]
