"""Safety and integrity helpers for the autonomous loop.

Bundles the audit's safety asks into a single module so it is easy to wire
into the orchestrator's guard pipeline:

- :func:`ethics_check` — flag comments mentioning bypass / data breach /
  unauthorized access / tracking without consent. Requires
  ``ETHICS-OVERRIDE: APPROVED`` from a maintainer to proceed.
- :func:`is_dangerous` — keyword scan from ``.github/dangerous_keywords.yml``;
  caller must respond with the ``FORCE: YES`` interlock pattern.
- :func:`requires_rationale` and :func:`extract_rationale` — enforce that
  every AI output includes a ``RATIONALE:`` line of >=10 words.
- :class:`ConstraintSet` — parse ``CONSTRAINT: <rule>`` markers, check
  that proposed actions don't violate stored constraints.
- :func:`needs_sentiment_clarification` — flag comments whose tone
  contradicts itself ("great but change everything").
- :class:`KnowledgeScore` — track source confidence across human signals.
"""

from __future__ import annotations

import dataclasses as _dc
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DANGEROUS_KEYWORDS_PATH = REPO_ROOT / ".github" / "dangerous_keywords.yml"
APPROVAL_TEAMS_PATH = REPO_ROOT / ".github" / "approval_teams.yml"
STYLE_GUIDE_PATH = REPO_ROOT / ".github" / "styleguide.yml"
KNOWLEDGE_SCORES_PATH = REPO_ROOT / "simulation" / "data" / "knowledge_scores.json"


# ---------------------------------------------------------------------------
# 5. Ethics check.
# ---------------------------------------------------------------------------

ETHICS_KEYWORDS = (
    "bypass auth",
    "bypass authentication",
    "data breach",
    "unauthorized access",
    "tracking without consent",
    "without consent",
    "scrape pii",
    "exfiltrate",
    "leak credentials",
    "disable audit",
)
ETHICS_OVERRIDE_RE = re.compile(r"(?im)^ETHICS-OVERRIDE:\s*APPROVED\b")
ETHICS_VIOLATION_MARKER = "ETHICS-VIOLATION"


@dataclass
class EthicsVerdict:
    triggered: bool
    matched: list[str] = field(default_factory=list)
    has_override: bool = False


def ethics_check(text: str) -> EthicsVerdict:
    if not text:
        return EthicsVerdict(False)
    lowered = text.lower()
    matched = [kw for kw in ETHICS_KEYWORDS if kw in lowered]
    if not matched:
        return EthicsVerdict(False)
    return EthicsVerdict(
        triggered=True,
        matched=matched,
        has_override=bool(ETHICS_OVERRIDE_RE.search(text)),
    )


# ---------------------------------------------------------------------------
# 16. Dangerous keyword scan.
# ---------------------------------------------------------------------------

FORCE_RE = re.compile(r"(?im)^FORCE:\s*YES\b")
DEFAULT_DANGEROUS = (
    "delete all data",
    "drop database",
    "disable authentication",
    "rm -rf /",
    "wipe filesystem",
    "format disk",
    "remove all users",
)


def _load_dangerous_keywords() -> tuple[str, ...]:
    if not DANGEROUS_KEYWORDS_PATH.exists() or yaml is None:
        return DEFAULT_DANGEROUS
    data = yaml.safe_load(DANGEROUS_KEYWORDS_PATH.read_text()) or {}
    items = data.get("dangerous_keywords") if isinstance(data, dict) else None
    if not items:
        return DEFAULT_DANGEROUS
    return tuple(str(item).lower() for item in items)


def is_dangerous(text: str) -> tuple[bool, list[str]]:
    if not text:
        return False, []
    lowered = text.lower()
    matched = [kw for kw in _load_dangerous_keywords() if kw in lowered]
    return bool(matched), matched


def is_force_acknowledged(text: str) -> bool:
    return bool(FORCE_RE.search(text or ""))


# ---------------------------------------------------------------------------
# 20. RATIONALE requirement.
# ---------------------------------------------------------------------------

RATIONALE_RE = re.compile(r"(?im)^RATIONALE:\s*(?P<body>\S.*)$")
RATIONALE_MIN_WORDS = 10


def extract_rationale(text: str) -> str | None:
    """Return the most recent RATIONALE: body, or None if absent/too short."""
    found: str | None = None
    for match in RATIONALE_RE.finditer(text or ""):
        candidate = match.group("body").strip()
        if len(candidate.split()) >= RATIONALE_MIN_WORDS:
            found = candidate
    return found


def requires_rationale(text: str) -> tuple[bool, str]:
    rationale = extract_rationale(text or "")
    if rationale:
        return True, rationale
    return False, ""


# ---------------------------------------------------------------------------
# 21. Constraints.
# ---------------------------------------------------------------------------

CONSTRAINT_RE = re.compile(r"(?im)^CONSTRAINT:\s*(?P<rule>\S.*)$")
CONSTRAINT_VIOLATION_MARKER = "CONSTRAINT-VIOLATION"


@dataclass
class ConstraintSet:
    rules: list[str] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> "ConstraintSet":
        return cls(rules=[m.group("rule").strip() for m in CONSTRAINT_RE.finditer(text or "")])

    def violations(self, action_text: str) -> list[str]:
        """Return rules that the proposed action text appears to break.

        Each rule is reduced to its "forbidden phrase" (the bit after
        ``do not`` / ``must not`` / ``never``). We then check whether a
        meaningful share of the phrase's content words appears in the
        action text. A direct substring match counts; for paraphrased
        action text we fall back to a content-word overlap threshold
        (>=60%) over words of length >=4. That is loose enough to catch
        ``add a new top-level dependency`` as violating
        ``do not introduce new top-level dependencies``.
        """
        if not action_text:
            return []
        out: list[str] = []
        lowered = action_text.lower()
        action_tokens = {tok for tok in _TOKEN_RE.findall(lowered) if len(tok) >= 4}
        for rule in self.rules:
            forbidden = _extract_forbidden_phrase(rule)
            if not forbidden:
                continue
            if forbidden in lowered:
                out.append(rule)
                continue
            phrase_tokens = {
                _stem(tok) for tok in _TOKEN_RE.findall(forbidden) if len(tok) >= 4
            }
            if not phrase_tokens:
                continue
            action_stems = {_stem(tok) for tok in action_tokens}
            shared = phrase_tokens & action_stems
            if len(shared) / max(len(phrase_tokens), 1) >= 0.6:
                out.append(rule)
        return out


_FORBIDDEN_PATTERN = re.compile(r"(?:must not|do not|never|forbid(?:den)?|no)\s+(?P<phrase>[^.\n]+)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")


def _stem(token: str) -> str:
    """Crude stemmer: strip a trailing 's' or 'es' so singular/plural collapse."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _extract_forbidden_phrase(rule: str) -> str:
    match = _FORBIDDEN_PATTERN.search(rule)
    if not match:
        return ""
    return match.group("phrase").strip().rstrip(".").lower()


# ---------------------------------------------------------------------------
# 8. Sentiment clarification.
# ---------------------------------------------------------------------------

POSITIVE_HINTS = ("great", "perfect", "love this", "looks awesome", "well done")
NEGATIVE_HINTS = ("change everything", "rewrite", "scrap", "throw away", "redo it all")


def needs_sentiment_clarification(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    has_pos = any(p in lowered for p in POSITIVE_HINTS)
    has_neg = any(n in lowered for n in NEGATIVE_HINTS)
    return has_pos and has_neg


def sentiment_clarification_template(items: list[str]) -> str:
    """Render a structured checklist asking the human to disambiguate."""
    lines = [
        "Your comment contains both positive and negative signals.",
        "Please check exactly the items you want kept, leave the rest unchecked:",
        "",
    ]
    for item in items or ["keep design", "keep implementation", "change architecture", "change scope"]:
        lines.append(f"- [ ] {item}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 19. Knowledge confidence.
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeScore:
    """Mutable confidence map persisted to ``knowledge_scores.json``."""

    path: Path = KNOWLEDGE_SCORES_PATH

    def load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}

    def save(self, scores: Mapping[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(scores), indent=2, sort_keys=True))

    def bump(self, source: str, delta: float) -> float:
        scores = self.load()
        new_score = max(0.0, min(1.0, scores.get(source, 0.5) + delta))
        scores[source] = new_score
        self.save(scores)
        return new_score

    def should_use(self, source: str, *, floor: float = 0.2) -> bool:
        return self.load().get(source, 0.5) >= floor


__all__ = [
    "APPROVAL_TEAMS_PATH",
    "ConstraintSet",
    "DANGEROUS_KEYWORDS_PATH",
    "ETHICS_VIOLATION_MARKER",
    "EthicsVerdict",
    "KNOWLEDGE_SCORES_PATH",
    "KnowledgeScore",
    "RATIONALE_MIN_WORDS",
    "STYLE_GUIDE_PATH",
    "ethics_check",
    "extract_rationale",
    "is_dangerous",
    "is_force_acknowledged",
    "needs_sentiment_clarification",
    "requires_rationale",
    "sentiment_clarification_template",
]
