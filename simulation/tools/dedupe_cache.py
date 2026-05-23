"""Standalone selector-wedge fix combining dedupe + stall + state-hash.

Mirrors the API shape the audit spec requested: a single
``DedupeCache`` class that owns three caches:

- ``records``         — ``(action, persona, target) → list[timestamp]``
  so the loop can refuse a duplicate within a configurable expiry window.
- ``stall_counter``   — per-issue counter that increments when the state
  hash matches the previous tick.
- ``state_hash_cache`` — per-issue SHA-256 of ``(body, updatedAt, labels)``.

The split helpers in :mod:`simulation.tools.loop_speedup` (``DedupeCache``,
``StallTracker``, ``issue_state_hash``) remain the ones wired into
:func:`simulation.tools.next_prompt_orchestrator.check_locks_and_cycles`.
This file is the unified entry-point so a single import buys the full
selector-wedge defence — and the audit-spec snippets keep working as-is.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from simulation.tools.loop_speedup import DEFAULT_DEDUPE_WINDOW_MIN

logger = logging.getLogger(__name__)

STALL_LIMIT = 3


class DedupeCache:
    """Selector-wedge defence — dedupe + stall + state hash in one object.

    Three caches live on the same instance because they all participate
    in the same decision: "should this tick be allowed to act on this
    issue?". Splitting them across modules is fine for testing, but the
    production-wiring callers want a single import.
    """

    def __init__(self, expiry_minutes: int = DEFAULT_DEDUPE_WINDOW_MIN) -> None:
        self.expiry = timedelta(minutes=expiry_minutes)
        self.records: dict[str, list[datetime]] = defaultdict(list)
        self.stall_counter: dict[int, int] = defaultdict(int)
        self.state_hash_cache: dict[int, str] = {}

    # -- key + dedupe -----------------------------------------------------

    def _key(self, action: str, persona: str, target: str | int) -> str:
        return f"{action}|{persona}|{target}"

    def is_duplicate(self, action: str, persona: str, target: str | int) -> bool:
        """Return True iff this (action, persona, target) was seen recently.

        Side-effect: on a non-duplicate call, the current timestamp is
        appended to the cache so the next call within ``expiry`` is
        treated as a dupe. This matches the audit-spec semantics — the
        first call "claims" the slot.
        """
        key = self._key(action, persona, target)
        now = datetime.now(tz=timezone.utc)
        self.records[key] = [ts for ts in self.records[key] if now - ts < self.expiry]
        if self.records[key]:
            return True
        self.records[key].append(now)
        return False

    def clear(self) -> None:
        """Reset every cache (useful in tests)."""
        self.records.clear()
        self.stall_counter.clear()
        self.state_hash_cache.clear()

    # -- stall counter ----------------------------------------------------

    def increment_stall(self, issue_id: int) -> int:
        self.stall_counter[issue_id] += 1
        return self.stall_counter[issue_id]

    def reset_stall(self, issue_id: int) -> None:
        self.stall_counter[issue_id] = 0

    def get_stall_count(self, issue_id: int) -> int:
        return self.stall_counter.get(issue_id, 0)

    # -- state hash -------------------------------------------------------

    def update_state_hash(self, issue_id: int, new_hash: str) -> bool:
        """Return True iff the hash for ``issue_id`` differs from the prior one."""
        old = self.state_hash_cache.get(issue_id)
        self.state_hash_cache[issue_id] = new_hash
        return old != new_hash


def get_issue_state_hash(issue: dict[str, Any]) -> str:
    """SHA-256 over the canonical state fields of an issue dict.

    Mirrors :func:`simulation.tools.loop_speedup.issue_state_hash` under
    the audit-spec function name so the operator's snippets keep
    working without an import-path rewrite.
    """
    body = issue.get("body") or ""
    updated = issue.get("updatedAt") or issue.get("updated_at") or ""
    labels = sorted(
        (label.get("name", "") if isinstance(label, dict) else str(label))
        for label in (issue.get("labels") or [])
    )
    payload = f"{body}_{updated}_{labels}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_DEDUPE_WINDOW_MIN",
    "DedupeCache",
    "STALL_LIMIT",
    "get_issue_state_hash",
]
