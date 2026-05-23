"""Loop-speedup helpers derived from 45 real autonomous-loop iterations.

Each helper here addresses a specific finding from `iteration-log.md`. They
are pure and side-effect-free unless they explicitly take a `gh` runner so
the test suite can exercise every code path without GitHub.

The big findings were:

- ``resolve_priority`` returns the first selector match with no per-tick
  dedupe; running the same (action, persona, target) twice within ~2 hours
  is the most common stall mode.
- Some action schemas were missing, so the validator returned
  ``valid=false`` for legitimate output.
- The same issue body kept selecting the same target because state had
  not actually changed between ticks.
- The CoT requirement was applied uniformly even for trivial typos.
- The agent re-sent the entire prompt prefix (hard caps, persona catalog)
  on every call.
- Each action consumed one round-trip to the model; chains like
  implement → review → merge → close took four iterations instead of one.

This module is the home for the dedupe cache, state-hash + stall counter,
policy-label inference, history truncation, prompt-caching hint helper,
and the ``CHAIN-NEXT:`` marker primitives.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from simulation.tools import validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 2. Auto-apply policy labels.
# ---------------------------------------------------------------------------

POLICY_LABEL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("risk:high", ("high risk", "operating-model", "agent-governance", "branch protection")),
    ("area:agent-governance", ("agent-governance", "operating model", "persona prompt")),
    ("area:security", ("auth", "credential", "secret", "token rotation")),
    ("area:performance", ("latency", "throughput", "n+1", "cache hit")),
    ("risk:critical", ("data breach", "production down", "outage")),
)


def infer_policy_labels(issue: dict[str, Any]) -> list[str]:
    """Return labels that should be on an issue but currently are not."""
    body_lower = ((issue.get("body") or "") + " " + (issue.get("title") or "")).lower()
    current = {label.get("name", "") for label in issue.get("labels") or []}
    out: list[str] = []
    for label, keywords in POLICY_LABEL_RULES:
        if label in current:
            continue
        if any(keyword in body_lower for keyword in keywords):
            out.append(label)
    return out


# ---------------------------------------------------------------------------
# 4. Duplicate-persona-post dedupe.
# ---------------------------------------------------------------------------

DEFAULT_DEDUPE_WINDOW_MIN = 120


@dataclass
class DedupeCache:
    """Process-local store of (persona, target, action) timestamps."""

    window_minutes: int = DEFAULT_DEDUPE_WINDOW_MIN
    _store: dict[tuple[str, str, str], list[float]] = field(default_factory=lambda: defaultdict(list))

    def _now(self) -> float:
        return time.time()

    def is_duplicate(self, persona: str, target: str | int, action: str) -> bool:
        key = (persona, str(target), action)
        window_seconds = self.window_minutes * 60
        cutoff = self._now() - window_seconds
        # Drop expired entries lazily.
        self._store[key] = [ts for ts in self._store[key] if ts >= cutoff]
        return len(self._store[key]) > 0

    def record(self, persona: str, target: str | int, action: str) -> None:
        key = (persona, str(target), action)
        self._store[key].append(self._now())


# ---------------------------------------------------------------------------
# 5. State-change stall detection.
# ---------------------------------------------------------------------------

STALL_LIMIT = 2


def issue_state_hash(issue: dict[str, Any]) -> str:
    """SHA-256 over body + updatedAt + labels — collapses unchanged state."""
    labels = sorted(label.get("name", "") for label in issue.get("labels") or [])
    payload = "|".join(
        [
            issue.get("body") or "",
            str(issue.get("updatedAt") or issue.get("updated_at") or ""),
            ",".join(labels),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class StallTracker:
    """Bumps a counter when an issue's hash hasn't moved between ticks."""

    limit: int = STALL_LIMIT
    _last_hash: dict[int, str] = field(default_factory=dict)
    _stall: dict[int, int] = field(default_factory=lambda: defaultdict(int))

    def observe(self, issue: dict[str, Any]) -> tuple[bool, int]:
        """Return ``(should_skip, stall_count)`` for this issue."""
        number = int(issue.get("number", 0))
        current = issue_state_hash(issue)
        previous = self._last_hash.get(number)
        if previous == current:
            self._stall[number] += 1
        else:
            self._stall[number] = 0
        self._last_hash[number] = current
        return self._stall[number] > self.limit, self._stall[number]


# ---------------------------------------------------------------------------
# 6. Truncated history (refines :func:`optimization.truncate_history`).
# ---------------------------------------------------------------------------

MAX_BODY_CHARS = 500


def truncate_history(
    comments: Iterable[dict[str, Any]],
    *,
    max_markers: int = 5,
    max_human: int = 3,
) -> list[dict[str, Any]]:
    """Return the last marker-bearing comments + last human comments only."""
    markers: list[dict[str, Any]] = []
    humans: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body") or ""
        author = comment.get("author") or {}
        if isinstance(author, dict):
            is_bot = author.get("type", "User") != "User"
        else:
            is_bot = False
        if validator.parse_body(body).hits:
            markers.append(comment)
        elif not is_bot:
            humans.append(comment)
    return markers[-max_markers:] + humans[-max_human:]


def truncate_body(text: str, *, limit: int = MAX_BODY_CHARS) -> str:
    """Hard-cap a body to ``limit`` characters so prompts stay small."""
    if not text or len(text) <= limit:
        return text or ""
    return text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# 7. Prompt-caching scaffold for Anthropic SDK callers.
# ---------------------------------------------------------------------------

CACHE_SENTINEL = "<!-- CACHE -->"


def split_cacheable_prefix(prompt: str) -> tuple[str, str]:
    """Split ``prompt`` into ``(cacheable, dynamic)`` around the sentinel.

    Callers using the Anthropic SDK wrap the cacheable half in a
    ``cache_control`` block:

    .. code-block:: python

        prefix, dynamic = split_cacheable_prefix(prompt)
        client.messages.create(
            model="claude-opus-4-7",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": dynamic},
                ]},
            ],
        )

    The sentinel ``<!-- CACHE -->`` lives in the rendered prompt — when the
    base template includes it after the hard caps, every iteration reuses
    the prefix and only the dynamic tail is billed at full rate.
    """
    idx = prompt.find(CACHE_SENTINEL)
    if idx < 0:
        return "", prompt
    return prompt[:idx], prompt[idx + len(CACHE_SENTINEL) :]


# ---------------------------------------------------------------------------
# 8. Skip CoT for trivial tasks.
# ---------------------------------------------------------------------------

REQUIRE_COT_KEY = "require_cot"


def cot_requirements(issue: dict[str, Any]) -> dict[str, Any]:
    """Return the per-issue CoT contract.

    Trivial tasks (label ``trivial`` or ``quick-fix``) lower the bar to
    1 step × 3 words and explicitly mark CoT as *optional*; the validator
    will skip the reasoning check when ``require_cot`` is false.
    """
    labels = {label.get("name", "") for label in issue.get("labels") or []}
    if "trivial" in labels or "quick-fix" in labels:
        return {"min_steps": 1, "min_words_per_step": 3, REQUIRE_COT_KEY: False}
    if "complex" in labels or "risk:high" in labels or "risk:critical" in labels:
        return {"min_steps": 5, "min_words_per_step": 12, REQUIRE_COT_KEY: True}
    return {"min_steps": 3, "min_words_per_step": 8, REQUIRE_COT_KEY: True}


# ---------------------------------------------------------------------------
# 9. GitHub response cache (memory-only TTL).
# ---------------------------------------------------------------------------

DEFAULT_GH_TTL_SECONDS = 10


@dataclass
class GhResponseCache:
    """Tiny TTL cache so back-to-back ``gh`` reads return memoized output."""

    ttl_seconds: int = DEFAULT_GH_TTL_SECONDS
    _store: dict[tuple[str, ...], tuple[float, str]] = field(default_factory=dict)

    def get(self, key: tuple[str, ...]) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self.ttl_seconds:
            del self._store[key]
            return None
        return value

    def put(self, key: tuple[str, ...], value: str) -> None:
        self._store[key] = (time.time(), value)

    def call(
        self,
        runner: Callable[[list[str]], str],
        args: list[str],
    ) -> str:
        key = tuple(args)
        cached = self.get(key)
        if cached is not None:
            return cached
        out = runner(args)
        self.put(key, out)
        return out


# ---------------------------------------------------------------------------
# 10. Action chaining via CHAIN-NEXT marker.
# ---------------------------------------------------------------------------

CHAIN_NEXT_RE = re.compile(r"(?im)^CHAIN-NEXT:\s*(?P<action>[a-z_]+)\b")
MAX_CHAIN = 3
ALLOWED_CHAIN_ACTIONS = frozenset(
    {
        "review_pr",
        "merge_gate",
        "accept_pr",
        "merge_pr",
        "close_issue",
        "address_changes_requested",
        "consistency_check",
        "open_followup_issue",
        "request_clarification",
    }
)


@dataclass
class ChainPlan:
    """Outcome of inspecting an agent output for CHAIN-NEXT."""

    next_action: str | None
    chain_count: int
    exhausted: bool
    rejected_reason: str = ""


def parse_chain_next(body: str) -> str | None:
    match = CHAIN_NEXT_RE.search(body or "")
    if not match:
        return None
    return match.group("action").lower()


def evaluate_chain(
    body: str,
    *,
    chain_so_far: int,
    max_chain: int = MAX_CHAIN,
) -> ChainPlan:
    """Decide whether to follow a CHAIN-NEXT marker on the agent's output."""
    candidate = parse_chain_next(body)
    if candidate is None:
        return ChainPlan(next_action=None, chain_count=chain_so_far, exhausted=False)
    if chain_so_far >= max_chain:
        return ChainPlan(
            next_action=None,
            chain_count=chain_so_far,
            exhausted=True,
            rejected_reason=f"chain limit {max_chain} reached",
        )
    if candidate not in ALLOWED_CHAIN_ACTIONS:
        return ChainPlan(
            next_action=None,
            chain_count=chain_so_far,
            exhausted=False,
            rejected_reason=f"action {candidate!r} not in allowed chain set",
        )
    return ChainPlan(
        next_action=candidate,
        chain_count=chain_so_far + 1,
        exhausted=False,
    )


__all__ = [
    "ALLOWED_CHAIN_ACTIONS",
    "CACHE_SENTINEL",
    "ChainPlan",
    "DEFAULT_DEDUPE_WINDOW_MIN",
    "DEFAULT_GH_TTL_SECONDS",
    "DedupeCache",
    "GhResponseCache",
    "MAX_BODY_CHARS",
    "MAX_CHAIN",
    "REQUIRE_COT_KEY",
    "STALL_LIMIT",
    "StallTracker",
    "cot_requirements",
    "evaluate_chain",
    "infer_policy_labels",
    "issue_state_hash",
    "parse_chain_next",
    "split_cacheable_prefix",
    "truncate_body",
    "truncate_history",
]
