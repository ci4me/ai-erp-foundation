"""Multi-agent deliberation, voting, and conflict-resolution primitives.

The autonomous loop frequently faces disagreement: two reviewers vote
opposite ways, a designer rejects an implementation, an agent contradicts
a past decision. Without a structured way to surface and resolve those
disputes, the loop oscillates forever or merges without consensus.

What lives here
---------------

- :class:`Debate` — bounded structured debate with 3 rounds × 200 tokens
  per side and a final tally vote.
- :func:`tally_votes` — counts AGREE / DISAGREE / ABSTAIN markers and
  applies the maintainer tie-break rule.
- :func:`quorum_status` — checks whether a PR has the required number of
  distinct ``REVIEW-VERDICT: APPROVE`` markers.
- :func:`detect_retraction` and :func:`apply_retraction` — handle
  ``RETRACT: <marker-id>`` markers.
- :func:`pause_state` / :func:`resume_state` — the ``PAUSE`` / ``RESUME``
  lifecycle.
- :func:`peer_consensus_blocker` — when two distinct agents flag the same
  issue, attach a ``consensus-blocker`` label.
- :func:`default_decision` and :func:`reconsider` — "you decide" and
  "let's revisit" markers respectively.
- :func:`tally_counterproposals` — counterproposal vote winner.
- :class:`ConflictLog` — append disagreements + resolutions to
  ``conflicts.md`` for future training.
- :func:`maintainer_bypass` — parse ``BYPASS: <phase>`` markers.

All helpers are pure: GitHub I/O lives in the orchestrator. The structure
mirrors :mod:`simulation.tools.optimization` so it stays composable.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Debate.
# ---------------------------------------------------------------------------

MAX_DEBATE_ROUNDS = 3
MAX_DEBATE_TOKENS_PER_ROUND = 200


@dataclass
class DebateRound:
    side: str  # e.g. "pro" / "con" or agent id
    round_index: int  # 1-indexed
    tokens: int
    body: str


@dataclass
class Debate:
    """One bounded debate between two named sides."""

    topic: str
    pro: str
    con: str
    rounds: list[DebateRound] = field(default_factory=list)

    def add(self, side: str, body: str) -> DebateRound:
        if side not in (self.pro, self.con):
            raise ValueError(f"side {side!r} not in this debate")
        round_index = sum(1 for r in self.rounds if r.side == side) + 1
        if round_index > MAX_DEBATE_ROUNDS:
            raise ValueError(f"side {side!r} exceeded {MAX_DEBATE_ROUNDS} rounds")
        tokens = max(1, len(body.split()))
        if tokens > MAX_DEBATE_TOKENS_PER_ROUND:
            raise ValueError(
                f"round token cap {MAX_DEBATE_TOKENS_PER_ROUND} exceeded ({tokens})"
            )
        entry = DebateRound(side=side, round_index=round_index, tokens=tokens, body=body)
        self.rounds.append(entry)
        return entry

    def is_ready_for_vote(self) -> bool:
        pro_done = sum(1 for r in self.rounds if r.side == self.pro) >= MAX_DEBATE_ROUNDS
        con_done = sum(1 for r in self.rounds if r.side == self.con) >= MAX_DEBATE_ROUNDS
        return pro_done and con_done


# ---------------------------------------------------------------------------
# 2. Voting.
# ---------------------------------------------------------------------------


VOTE_RE = re.compile(
    r"(?im)^VOTE(?:\s*\[(?P<voter>[^\]]+)\])?:\s*(?P<choice>AGREE|DISAGREE|ABSTAIN|[A-Z0-9_-]+)\b"
)
MAINTAINER_LABEL = "role:maintainer"


@dataclass
class VoteTally:
    agree: int = 0
    disagree: int = 0
    abstain: int = 0
    proposal_votes: dict[str, int] = field(default_factory=dict)
    voters: list[str] = field(default_factory=list)
    winner: str | None = None
    tiebreak: str = ""


def tally_votes(
    comments: Iterable[dict[str, Any]],
    *,
    maintainers: Iterable[str] = (),
) -> VoteTally:
    """Walk comments, extract VOTE markers, return a tally with a winner."""
    tally = VoteTally()
    maintainer_set = set(maintainers)
    last_maintainer_vote: str | None = None
    for comment in comments:
        body = comment.get("body") or ""
        author = comment.get("author", {}).get("login") if isinstance(comment.get("author"), dict) else comment.get("author") or ""
        for match in VOTE_RE.finditer(body):
            choice = match.group("choice").upper()
            voter = match.group("voter") or author or "anon"
            tally.voters.append(voter)
            if choice == "AGREE":
                tally.agree += 1
            elif choice == "DISAGREE":
                tally.disagree += 1
            elif choice == "ABSTAIN":
                tally.abstain += 1
            else:
                tally.proposal_votes[choice] = tally.proposal_votes.get(choice, 0) + 1
            if voter in maintainer_set:
                last_maintainer_vote = choice
    if tally.proposal_votes:
        tally.winner = max(tally.proposal_votes, key=tally.proposal_votes.get)
        return tally
    if tally.agree > tally.disagree:
        tally.winner = "AGREE"
    elif tally.disagree > tally.agree:
        tally.winner = "DISAGREE"
    else:
        if last_maintainer_vote is not None:
            tally.winner = last_maintainer_vote
            tally.tiebreak = "maintainer"
        else:
            tally.winner = "TIE"
            tally.tiebreak = "needs_human"
    return tally


def tally_counterproposals(comments: Iterable[dict[str, Any]]) -> VoteTally:
    """Counterproposal voting is a thin wrapper that ignores AGREE/DISAGREE."""
    return tally_votes(comments)


# ---------------------------------------------------------------------------
# Quorum for PR approval.
# ---------------------------------------------------------------------------

REQUIRED_DISTINCT_APPROVALS = 2
HUMAN_APPROVAL_OVERRIDES_QUORUM = 1


@dataclass
class QuorumStatus:
    ok: bool
    approvals: int
    human_approvals: int
    distinct_approvers: list[str]
    needs_more: int


def quorum_status(
    review_comments: Iterable[dict[str, Any]],
    *,
    human_logins: Iterable[str] = (),
) -> QuorumStatus:
    """Return whether ``review_comments`` satisfy the approval quorum."""
    approvers: dict[str, bool] = {}
    human_count = 0
    human_set = set(human_logins)
    for comment in review_comments:
        body = comment.get("body") or ""
        if not re.search(r"(?im)^REVIEW-VERDICT:\s*APPROVE(?:_WITH_CONDITIONS)?\b", body):
            continue
        author = comment.get("author", {}).get("login") if isinstance(comment.get("author"), dict) else comment.get("author") or "anon"
        is_human = author in human_set
        approvers[author] = approvers.get(author, False) or is_human
        if is_human:
            human_count += 1
    distinct = list(approvers)
    if human_count >= HUMAN_APPROVAL_OVERRIDES_QUORUM:
        return QuorumStatus(True, len(distinct), human_count, distinct, 0)
    needs = max(0, REQUIRED_DISTINCT_APPROVALS - len(distinct))
    return QuorumStatus(needs == 0, len(distinct), human_count, distinct, needs)


# ---------------------------------------------------------------------------
# 3. Retraction.
# ---------------------------------------------------------------------------

RETRACT_RE = re.compile(r"(?im)^RETRACT:\s*(?P<id>[A-Za-z0-9_/#.:-]+)\b")


def detect_retraction(text: str) -> list[str]:
    """Return all marker IDs that this text retracts."""
    return [m.group("id") for m in RETRACT_RE.finditer(text)]


def apply_retraction(
    state: dict[str, Any],
    retracted_ids: Iterable[str],
) -> dict[str, Any]:
    """Remove retracted entries from a state object's history list (idempotent)."""
    history = list(state.get("history") or [])
    survivors = [entry for entry in history if entry.get("id") not in set(retracted_ids)]
    new_state = dict(state)
    new_state["history"] = survivors
    new_state["retracted"] = sorted(set(retracted_ids))
    return new_state


# ---------------------------------------------------------------------------
# 4. Pause / Resume.
# ---------------------------------------------------------------------------

PAUSE_RE = re.compile(r"(?im)^PAUSE:\s*(?P<reason>\S.*)$")
RESUME_RE = re.compile(r"(?im)^RESUME(?::\s*(?P<reason>\S.*))?$")
PAUSE_LABEL = "paused"


def pause_state(
    issue: dict[str, Any],
) -> tuple[bool, str]:
    """Return ``(paused?, reason)`` reflecting the most recent pause/resume."""
    events: list[tuple[str, str]] = []
    body = issue.get("body") or ""
    for match in PAUSE_RE.finditer(body):
        events.append(("pause", match.group("reason")))
    for match in RESUME_RE.finditer(body):
        events.append(("resume", match.group("reason") or ""))
    for comment in issue.get("comments") or []:
        cbody = comment.get("body") or ""
        for match in PAUSE_RE.finditer(cbody):
            events.append(("pause", match.group("reason")))
        for match in RESUME_RE.finditer(cbody):
            events.append(("resume", match.group("reason") or ""))
    if not events:
        return False, ""
    last_kind, last_reason = events[-1]
    return (last_kind == "pause", last_reason)


# ---------------------------------------------------------------------------
# 9. Peer escalation / consensus blocker.
# ---------------------------------------------------------------------------

_SIMILARITY_TOKEN_RE = re.compile(r"[A-Za-z0-9]{3,}")


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in _SIMILARITY_TOKEN_RE.findall(text)}


def jaccard_similarity(a: str, b: str) -> float:
    """Cheap-and-cheerful similarity (no embedding model in this sandbox)."""
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    intersect = len(ta & tb)
    union = len(ta | tb)
    return intersect / union if union else 0.0


def peer_consensus_blocker(
    comments: Iterable[dict[str, Any]],
    *,
    similarity_threshold: float = 0.8,
) -> list[tuple[str, str, float]]:
    """Return ``(author_a, author_b, similarity)`` pairs that agreed strongly."""
    items: list[tuple[str, str]] = []
    for comment in comments:
        body = comment.get("body") or ""
        author = comment.get("author") or "anon"
        if isinstance(author, dict):
            author = author.get("login") or "anon"
        items.append((author, body))
    matches: list[tuple[str, str, float]] = []
    for i, (a1, b1) in enumerate(items):
        for a2, b2 in items[i + 1 :]:
            if a1 == a2:
                continue
            sim = jaccard_similarity(b1, b2)
            if sim >= similarity_threshold:
                matches.append((a1, a2, sim))
    return matches


# ---------------------------------------------------------------------------
# 10. Default decision.
# ---------------------------------------------------------------------------

DEFAULT_DECISION_RE = re.compile(r"(?im)^DEFAULT-APPLIED:\s*(?P<choice>\S.*)$")
OVERRIDE_RE = re.compile(r"(?im)^OVERRIDE:\s*(?P<choice>\S.*)$")
DEFAULT_TRIGGER_PHRASES = ("i don't care", "you decide", "your call", "whatever you think")


def is_default_request(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in DEFAULT_TRIGGER_PHRASES)


def latest_default(comments: Iterable[dict[str, Any]]) -> str | None:
    """Return the most recent DEFAULT-APPLIED choice (overridable by OVERRIDE)."""
    chosen: str | None = None
    for comment in comments:
        body = comment.get("body") or ""
        for match in DEFAULT_DECISION_RE.finditer(body):
            chosen = match.group("choice").strip()
        for match in OVERRIDE_RE.finditer(body):
            chosen = match.group("choice").strip()
    return chosen


# ---------------------------------------------------------------------------
# 11. Reconsider.
# ---------------------------------------------------------------------------

RECONSIDER_RE = re.compile(r"(?im)^RECONSIDER:\s*(?P<evidence>\S.*)$")
RECONSIDER_APPROVED_RE = re.compile(r"(?im)^RECONSIDER-APPROVED\b")


def reconsider_state(text: str) -> tuple[bool, bool, str]:
    """Return (reconsider_requested, approved, evidence)."""
    evidence_match = RECONSIDER_RE.search(text)
    if not evidence_match:
        return False, False, ""
    return True, bool(RECONSIDER_APPROVED_RE.search(text)), evidence_match.group("evidence")


# ---------------------------------------------------------------------------
# Conflict log.
# ---------------------------------------------------------------------------


@dataclass
class ConflictLog:
    """Append-only ledger of disagreements and their resolutions."""

    path: Path

    def append(self, *, topic: str, sides: dict[str, str], resolution: str) -> None:
        ts = _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        block = [
            f"## {ts} — {topic}",
            "",
        ]
        for side, position in sides.items():
            block.append(f"- **{side}**: {position}")
        block.append("")
        block.append(f"**Resolution:** {resolution}")
        block.append("")
        existing = self.path.read_text() if self.path.exists() else "# Conflict log\n\n"
        self.path.write_text(existing + "\n".join(block) + "\n")


# ---------------------------------------------------------------------------
# 28. Maintainer bypass.
# ---------------------------------------------------------------------------

BYPASS_RE = re.compile(r"(?im)^BYPASS:\s*(?P<phase>REVIEW|MERGE_GATE|TRIAGE|DESIGN|ACCEPTANCE)\b")
BYPASS_LOG_PATH = Path(".bypass_log")


def detect_bypass(text: str) -> list[str]:
    return [m.group("phase").upper() for m in BYPASS_RE.finditer(text)]


def log_bypass(phase: str, *, by: str, reason: str, path: Path | None = None) -> None:
    """Append a bypass record to ``.bypass_log`` for audit."""
    target = path or BYPASS_LOG_PATH
    ts = _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts}\t{by}\t{phase}\t{reason}\n"
    with target.open("a") as fh:
        fh.write(line)


__all__ = [
    "BYPASS_RE",
    "ConflictLog",
    "Debate",
    "DebateRound",
    "MAX_DEBATE_ROUNDS",
    "MAX_DEBATE_TOKENS_PER_ROUND",
    "PAUSE_LABEL",
    "QuorumStatus",
    "VoteTally",
    "apply_retraction",
    "detect_bypass",
    "detect_retraction",
    "is_default_request",
    "jaccard_similarity",
    "latest_default",
    "log_bypass",
    "pause_state",
    "peer_consensus_blocker",
    "quorum_status",
    "reconsider_state",
    "tally_counterproposals",
    "tally_votes",
]
