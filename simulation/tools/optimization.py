"""Token-efficiency and loop-convergence helpers for the autonomous loop.

This module consolidates several small concerns that all share one motivation:
keep the loop *short* and *terminating*. Each helper is independently usable
and pure (no GitHub I/O) so the orchestrator can compose them without owning
their state.

What lives here
---------------

- :func:`quick_fix_bypass` — fast-path trivial issues straight to implement.
- :func:`detect_off_topic` — guard against obviously-irrelevant comments.
- :func:`classify_intent` — keyword classifier for prose-only approvals
  ("looks good", "please merge", ...).
- :func:`is_style_only_review` — feedback is all whitespace/naming/comments.
- :func:`style_round_state` — track style-only rounds across reviews.
- :func:`extract_markers_priority` — return all markers ordered by priority,
  with ``URGENT`` always moved to the front.
- :func:`feedback_hash` — normalize feedback text and compute a stable hash
  so we can detect identical feedback repeated across cycles.
- :func:`state_hash` — SHA-256 of the issue state (phase + counters + last
  marker) for the global "stuck counter" loop breaker.
- :func:`truncate_history` — clip GitHub comments to the last 5 markers +
  last 5 human messages.
- :func:`is_stale_clarification` — issue has ``awaiting-human`` label and
  hasn't moved in 48 hours.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from simulation.tools import validator

# ---------------------------------------------------------------------------
# 1. Quick-fix bypass.
# ---------------------------------------------------------------------------

TEAM_REQUEST_RE = re.compile(r"(?im)^TEAM-REQUEST:\s*(\S.*)$")
TRIVIAL_LABELS = frozenset({"trivial", "quick-fix", "typo"})
TRIVIAL_PHRASES = ("typo", "fix readme", "small change", "fix typo")


def quick_fix_bypass(issue: dict[str, Any]) -> bool:
    """True when an issue is trivial enough to skip triage + design.

    The check is conservative — both signals must agree:

    1. A ``TEAM-REQUEST:`` marker exists in the body (human escalation).
    2. The issue is tagged with a trivial-class label OR the body/title
       contains a known trivial phrase.
    """
    body = (issue.get("body") or "") + "\n" + (issue.get("title") or "")
    if not TEAM_REQUEST_RE.search(body):
        return False
    labels = {label.get("name", "") for label in issue.get("labels") or []}
    if TRIVIAL_LABELS & labels:
        return True
    lowered = body.lower()
    return any(phrase in lowered for phrase in TRIVIAL_PHRASES)


# ---------------------------------------------------------------------------
# 11. Off-topic detection.
# ---------------------------------------------------------------------------

OFF_TOPIC_KEYWORDS = (
    "weather",
    "sports",
    "movie",
    "celebrity",
    "horoscope",
    "recipe",
    "lottery",
)
OFF_TOPIC_RESPONSE = (
    "Please stay on topic. Use `TEAM-REQUEST:` for new work."
)


def detect_off_topic(text: str) -> bool:
    """Return True if ``text`` looks like off-topic chit-chat."""
    if not text:
        return False
    lowered = text.lower()
    return any(needle in lowered for needle in OFF_TOPIC_KEYWORDS)


# ---------------------------------------------------------------------------
# 7. Natural-language fallback / intent classifier.
# ---------------------------------------------------------------------------

INTENT_RULES: tuple[tuple[str, str, float], ...] = (
    # (marker target, keyword phrase, confidence weight)
    ("REVIEW-VERDICT: APPROVE", "looks good", 0.85),
    ("REVIEW-VERDICT: APPROVE", "lgtm", 0.95),
    ("REVIEW-VERDICT: APPROVE", "ship it", 0.9),
    ("REVIEW-VERDICT: APPROVE", "approved", 0.92),
    ("REVIEW-VERDICT: APPROVE", "please merge", 0.95),
    ("REVIEW-VERDICT: REQUEST_CHANGES", "please change", 0.85),
    ("REVIEW-VERDICT: REQUEST_CHANGES", "needs fix", 0.85),
    ("REVIEW-VERDICT: BLOCKED", "do not merge", 0.92),
    ("ACCEPTANCE-DECISION: ACCEPT", "go ahead", 0.85),
    ("ACCEPTANCE-DECISION: REJECT", "rejected", 0.9),
)


@dataclass
class IntentGuess:
    suggested_marker: str
    confidence: float
    matched_phrase: str


def classify_intent(text: str) -> IntentGuess | None:
    """Return the best marker guess for prose-only feedback.

    Confidence floor of 0.8 is enforced by the caller (the orchestrator),
    not here, so this stays useful for inspection/logging.
    """
    if not text:
        return None
    lowered = text.lower()
    parse = validator.parse_body(text, comment_length=len(text))
    if parse.hits:
        return None  # already has a structured marker
    best: IntentGuess | None = None
    for marker, phrase, confidence in INTENT_RULES:
        if phrase in lowered:
            if best is None or confidence > best.confidence:
                best = IntentGuess(
                    suggested_marker=marker,
                    confidence=confidence,
                    matched_phrase=phrase,
                )
    return best


# ---------------------------------------------------------------------------
# 5. Style-only approval limit.
# ---------------------------------------------------------------------------

STYLE_KEYWORDS = (
    "whitespace",
    "indentation",
    "indent",
    "naming",
    "rename",
    "comment ",
    "comments",
    "docstring",
    "formatting",
    "format",
    "spacing",
    "trailing",
    "blank line",
    "newline",
    "lowercase",
    "uppercase",
    "camelcase",
    "snake_case",
    "lint",
)
NON_STYLE_KEYWORDS = (
    "logic",
    "bug",
    "race",
    "security",
    "vulnerab",
    "missing",
    "incorrect",
    "broken",
    "fail",
    "crash",
    "leak",
    "regression",
    "performance",
    "n+1",
    "deadlock",
)


def is_style_only_review(text: str) -> bool:
    """True if review feedback only touches style, not logic/bugs."""
    if not text:
        return False
    lowered = text.lower()
    style_hits = sum(1 for kw in STYLE_KEYWORDS if kw in lowered)
    non_style_hits = sum(1 for kw in NON_STYLE_KEYWORDS if kw in lowered)
    return style_hits >= 1 and non_style_hits == 0


STYLE_ROUND_LABEL_PREFIX = "style_round:"
STYLE_ROUND_AUTO_APPROVE = 3


def style_round_count(labels: Iterable[str]) -> int:
    """Read the style-round counter from a label set."""
    for label in labels:
        if label.startswith(STYLE_ROUND_LABEL_PREFIX):
            try:
                return int(label.split(":", 1)[1])
            except ValueError:
                continue
    return 0


def should_auto_approve_style(count: int) -> bool:
    return count >= STYLE_ROUND_AUTO_APPROVE


# ---------------------------------------------------------------------------
# 14. Multiple markers / URGENT priority.
# ---------------------------------------------------------------------------

MARKER_PRIORITY = (
    "TEAM-REQUEST",
    "URGENT",
    "REVIEW-VERDICT",
    "DESIGN-APPROVAL",
    "ACCEPTANCE-DECISION",
    "MERGE-STATUS",
    "ISSUE-CLOSED",
)


def extract_markers_priority(body: str) -> list[validator.MarkerHit]:
    """Return all markers in priority order; URGENT always moves to front.

    Two markers are recognized here that are *not* in the catalog because
    they are human-side request signals, not agent outputs:

    - ``TEAM-REQUEST`` — a human escalation / new-work marker. We include
      it so :data:`MARKER_PRIORITY` can rank it above agent verdicts.
    - ``URGENT`` — a queue-jump marker that always lands at index 0.
    """
    parse = validator.parse_body(body)
    hits = list(parse.hits)

    team_request_re = re.compile(r"(?im)^TEAM-REQUEST:\s*(\S.*)$")
    for match in team_request_re.finditer(body):
        line_no = body[: match.start()].count("\n") + 1
        hits.append(
            validator.MarkerHit(
                marker="TEAM-REQUEST",
                value="",
                action_id="team_request",
                line_number=line_no,
                raw_line=match.group(0),
            )
        )

    urgent_re = re.compile(r"(?im)^URGENT:\s*\S", re.IGNORECASE)
    has_urgent = bool(urgent_re.search(body))

    def rank(hit: validator.MarkerHit) -> tuple[int, int]:
        try:
            primary = MARKER_PRIORITY.index(hit.marker)
        except ValueError:
            primary = len(MARKER_PRIORITY)
        return (primary, hit.line_number)

    hits.sort(key=rank)
    if has_urgent:
        urgent_pseudo = validator.MarkerHit(
            marker="URGENT",
            value="TRUE",
            action_id="urgent",
            line_number=0,
            raw_line="URGENT",
        )
        hits.insert(0, urgent_pseudo)
    return hits


# ---------------------------------------------------------------------------
# 12. Identical-feedback hash.
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_RUN_ID_RE = re.compile(r"Run-ID:\s*\S+")
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?")


def _normalize_for_hash(text: str) -> str:
    """Strip volatile bits (run IDs, timestamps, whitespace) before hashing."""
    text = _RUN_ID_RE.sub("Run-ID: <stripped>", text)
    text = _TIMESTAMP_RE.sub("<ts>", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip().lower()


def feedback_hash(text: str) -> str:
    """Compute a stable SHA-256 hash of feedback text after normalization."""
    normalized = _normalize_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def detect_identical_feedback(history: list[str]) -> bool:
    """True if the last two non-empty feedback bodies hash to the same value."""
    hashed = [feedback_hash(item) for item in history if item.strip()]
    return len(hashed) >= 2 and hashed[-1] == hashed[-2]


# ---------------------------------------------------------------------------
# 15. State-hash loop breaker.
# ---------------------------------------------------------------------------


def state_hash(state: dict[str, Any]) -> str:
    """Compute a SHA-256 over the canonical state fields used for cycle gating."""
    fields = {
        "phase": state.get("phase"),
        "design_loop_count": state.get("design_loop_count", 0),
        "implement_loop_count": state.get("implement_loop_count", 0),
        "last_marker": state.get("last_marker"),
        "labels": sorted(state.get("labels", [])),
    }
    canonical = "|".join(f"{k}={fields[k]}" for k in sorted(fields))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


STUCK_LABEL_PREFIX = "stuck_counter:"
STUCK_BREAK_THRESHOLD = 3


def stuck_count(labels: Iterable[str]) -> int:
    for label in labels:
        if label.startswith(STUCK_LABEL_PREFIX):
            try:
                return int(label.split(":", 1)[1])
            except ValueError:
                continue
    return 0


def should_break_loop(stuck: int) -> bool:
    return stuck >= STUCK_BREAK_THRESHOLD


# ---------------------------------------------------------------------------
# 6. Truncated history.
# ---------------------------------------------------------------------------

HISTORY_KEEP_MARKERS = 5
HISTORY_KEEP_HUMAN = 5


def truncate_history(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the last 5 marker-bearing comments + last 5 human comments.

    Marker-bearing comments are detected by running :func:`validator.parse_body`
    on each comment's body. Human comments are identified by ``isBot=False``
    or absence of the v0.3 YAML persona header. AI comments older than two
    turns are dropped.
    """
    marked: list[dict[str, Any]] = []
    human: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body") or ""
        is_bot = bool(comment.get("isBot")) or "Persona:" in body[:120]
        if validator.parse_body(body).hits:
            marked.append(comment)
        elif not is_bot:
            human.append(comment)
    keep = marked[-HISTORY_KEEP_MARKERS:] + human[-HISTORY_KEEP_HUMAN:]
    # Sort by original order using createdAt when available, else preserve.
    keep.sort(key=lambda c: c.get("createdAt") or "")
    if len(keep) < len(comments):
        keep.append(
            {
                "body": f"(... {len(comments) - len(keep)} older messages truncated)",
                "_synthetic": True,
            }
        )
    return keep


# ---------------------------------------------------------------------------
# 2. Output-doubling warning helper.
# ---------------------------------------------------------------------------


def output_doubled(previous_length: int, current_length: int) -> bool:
    """True when a follow-up output is >2x the size of the previous one."""
    if previous_length <= 0:
        return False
    return current_length > 2 * previous_length


# ---------------------------------------------------------------------------
# 3. Stale clarification timeout.
# ---------------------------------------------------------------------------

AWAITING_HUMAN_LABEL = "awaiting-human"
STALE_CLARIFICATION_HOURS = 48


def is_stale_clarification(
    issue: dict[str, Any],
    *,
    now: _dt.datetime | None = None,
    hours: int = STALE_CLARIFICATION_HOURS,
) -> bool:
    """True when an awaiting-human issue has been silent for too long."""
    labels = {label.get("name", "") for label in issue.get("labels") or []}
    if AWAITING_HUMAN_LABEL not in labels:
        return False
    updated = issue.get("updatedAt") or issue.get("updated_at")
    if not updated:
        return False
    try:
        if updated.endswith("Z"):
            ts = _dt.datetime.fromisoformat(updated[:-1]).replace(tzinfo=_dt.UTC)
        else:
            ts = _dt.datetime.fromisoformat(updated)
    except ValueError:
        return False
    moment = now or _dt.datetime.now(tz=_dt.UTC)
    return (moment - ts).total_seconds() >= hours * 3600


__all__ = [
    "AWAITING_HUMAN_LABEL",
    "IntentGuess",
    "MARKER_PRIORITY",
    "OFF_TOPIC_RESPONSE",
    "STUCK_BREAK_THRESHOLD",
    "STYLE_ROUND_AUTO_APPROVE",
    "classify_intent",
    "detect_identical_feedback",
    "detect_off_topic",
    "extract_markers_priority",
    "feedback_hash",
    "is_stale_clarification",
    "is_style_only_review",
    "output_doubled",
    "quick_fix_bypass",
    "should_auto_approve_style",
    "should_break_loop",
    "state_hash",
    "stuck_count",
    "style_round_count",
    "truncate_history",
]
