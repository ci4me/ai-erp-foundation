"""GitHub label-based locking for the autonomous loop.

Two scheduler instances racing on the same issue is a real failure mode: the
loop is triggered by CI, by humans, and by a cron sweep. This module provides
a coarse-grained lock keyed on a GitHub label so only one instance acts on a
given issue or PR at a time.

Design choices
--------------

- The lock is the *presence* of a single label (default ``agent-working``).
- ``acquire`` is atomic from GitHub's side: ``gh issue edit --add-label`` is
  idempotent; the lock owner is the first caller to *successfully add the
  label when it was not already there*. We detect that by re-reading labels
  after the edit and comparing to the snapshot we took beforehand.
- Locks have a wall-clock TTL so a crashed agent cannot deadlock the loop.
  Stale locks are reaped by ``release_stale``, which is called both inline
  on ``acquire`` and from a periodic GitHub Actions cleanup.
- Callers should use ``with held(...):`` so the label is removed even if the
  action raises.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterator

logger = logging.getLogger(__name__)

DEFAULT_LABEL = "agent-working"
DEFAULT_TTL_SECONDS = 5 * 60  # 5 minutes
LOCK_TIMESTAMP_LABEL_PREFIX = "agent-working-since-"


GhRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(args: list[str]) -> "subprocess.CompletedProcess[str]":
    if not shutil.which("gh"):
        raise RuntimeError("gh CLI is required for lock operations")
    return subprocess.run(["gh", *args], check=False, capture_output=True, text=True)


@dataclass
class LockState:
    """Snapshot of a lock attempt."""

    target: str  # "issue:42" or "pr:99"
    acquired: bool
    reason: str = ""
    held_by_label: str = ""


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.UTC)


def _parse_target(target: str) -> tuple[str, str]:
    kind, _, number = target.partition(":")
    if kind not in {"issue", "pr"} or not number.isdigit():
        raise ValueError(f"target must be 'issue:N' or 'pr:N', got {target!r}")
    return kind, number


def _list_labels(repo: str, target: str, runner: GhRunner) -> list[str]:
    kind, number = _parse_target(target)
    sub = "issue" if kind == "issue" else "pr"
    result = runner([sub, "view", number, "--repo", repo, "--json", "labels"])
    if result.returncode != 0:
        raise RuntimeError(f"gh {sub} view failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout or "{}")
    return [label["name"] for label in payload.get("labels", [])]


def _add_label(repo: str, target: str, label: str, runner: GhRunner) -> None:
    kind, number = _parse_target(target)
    sub = "issue" if kind == "issue" else "pr"
    result = runner([sub, "edit", number, "--repo", repo, "--add-label", label])
    if result.returncode != 0:
        raise RuntimeError(f"gh {sub} edit --add-label failed: {result.stderr.strip()}")


def _remove_label(repo: str, target: str, label: str, runner: GhRunner) -> None:
    kind, number = _parse_target(target)
    sub = "issue" if kind == "issue" else "pr"
    result = runner([sub, "edit", number, "--repo", repo, "--remove-label", label])
    if result.returncode != 0:
        logger.warning("gh %s edit --remove-label failed: %s", sub, result.stderr.strip())


def _timestamp_label(now: _dt.datetime | None = None) -> str:
    moment = now or _now_utc()
    return f"{LOCK_TIMESTAMP_LABEL_PREFIX}{moment.strftime('%Y%m%dT%H%M%SZ')}"


def _parse_timestamp_label(label: str) -> _dt.datetime | None:
    if not label.startswith(LOCK_TIMESTAMP_LABEL_PREFIX):
        return None
    raw = label[len(LOCK_TIMESTAMP_LABEL_PREFIX) :]
    try:
        return _dt.datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.UTC)
    except ValueError:
        return None


def _lock_is_stale(labels: list[str], ttl_seconds: int) -> bool:
    """True when the timestamp label is older than TTL or missing entirely."""
    now = _now_utc()
    for label in labels:
        ts = _parse_timestamp_label(label)
        if ts is None:
            continue
        if (now - ts).total_seconds() > ttl_seconds:
            return True
        return False
    # No timestamp label found alongside the lock — be conservative and treat
    # the lock as stale rather than risking a permanent deadlock.
    return True


def acquire(
    repo: str,
    target: str,
    *,
    label: str = DEFAULT_LABEL,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    runner: GhRunner | None = None,
) -> LockState:
    """Try to take the lock on ``target`` (``"issue:N"`` or ``"pr:N"``).

    GitHub's label API has no native compare-and-swap, so we synthesize one:

    1. Read the label set. If ``agent-working`` is present and its companion
       timestamp label is younger than ``ttl_seconds``, give up — another
       agent owns the lock.
    2. If the lock label is present *but* stale (timestamp older than TTL),
       reap it: removing both labels is idempotent and safe.
    3. Add ``agent-working`` and a fresh ``agent-working-since-<ts>`` label.
    4. Re-read the label set. If ``agent-working`` is missing or the timestamp
       we wrote is missing, another agent raced us and won — back off.
    5. If multiple ``-since-`` labels coexist, the *oldest* wins (it represents
       the agent that wrote first). If the earliest timestamp is not ours,
       remove our labels and report ``race-lost-older``.

    The double read at step 4 is what catches genuine races: GitHub will
    silently coalesce two ``--add-label`` calls for the same label name, but
    the timestamp suffix makes each agent's write distinguishable.
    """
    run = runner or _default_runner
    labels = _list_labels(repo, target, run)
    if label in labels and not _lock_is_stale(labels, ttl_seconds):
        return LockState(target=target, acquired=False, reason="already-locked", held_by_label=label)
    # Best-effort reap of an existing stale lock before re-acquiring. A stale
    # lock means an agent crashed mid-action; we cannot let the loop deadlock.
    if label in labels and _lock_is_stale(labels, ttl_seconds):
        _remove_label(repo, target, label, run)
        for existing in labels:
            if existing.startswith(LOCK_TIMESTAMP_LABEL_PREFIX):
                _remove_label(repo, target, existing, run)
    timestamp_label = _timestamp_label()
    _add_label(repo, target, label, run)
    _add_label(repo, target, timestamp_label, run)
    # Re-read labels to detect a race where another agent took the lock first.
    # We trust GitHub as the source of truth, not our local view.
    refreshed = _list_labels(repo, target, run)
    own_timestamps = [
        l for l in refreshed if l.startswith(LOCK_TIMESTAMP_LABEL_PREFIX)
    ]
    if label not in refreshed or timestamp_label not in own_timestamps:
        return LockState(target=target, acquired=False, reason="race-lost")
    # Oldest-writer-wins tie-break: if any timestamp label is strictly older
    # than ours, that agent acquired first. Releasing our labels here lets
    # the winner finish without us also hammering the issue.
    earliest = min(
        (ts for ts in (_parse_timestamp_label(l) for l in own_timestamps) if ts is not None),
        default=None,
    )
    ours = _parse_timestamp_label(timestamp_label)
    if earliest is not None and ours is not None and earliest < ours:
        _remove_label(repo, target, timestamp_label, run)
        _remove_label(repo, target, label, run)
        return LockState(target=target, acquired=False, reason="race-lost-older")
    return LockState(target=target, acquired=True, held_by_label=label)


def release(
    repo: str,
    target: str,
    *,
    label: str = DEFAULT_LABEL,
    runner: GhRunner | None = None,
) -> None:
    """Release the lock. Always safe to call; missing labels are ignored."""
    run = runner or _default_runner
    labels = _list_labels(repo, target, run)
    if label in labels:
        _remove_label(repo, target, label, run)
    for existing in labels:
        if existing.startswith(LOCK_TIMESTAMP_LABEL_PREFIX):
            _remove_label(repo, target, existing, run)


def release_stale(
    repo: str,
    target: str,
    *,
    label: str = DEFAULT_LABEL,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    runner: GhRunner | None = None,
) -> bool:
    """Reap an expired lock. Returns True when a release happened."""
    run = runner or _default_runner
    labels = _list_labels(repo, target, run)
    if label not in labels:
        return False
    if not _lock_is_stale(labels, ttl_seconds):
        return False
    release(repo, target, label=label, runner=run)
    return True


@contextlib.contextmanager
def held(
    repo: str,
    target: str,
    *,
    label: str = DEFAULT_LABEL,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    runner: GhRunner | None = None,
) -> Iterator[LockState]:
    """Context manager that acquires and always releases the lock."""
    state = acquire(repo, target, label=label, ttl_seconds=ttl_seconds, runner=runner)
    try:
        yield state
    finally:
        if state.acquired:
            release(repo, target, label=label, runner=runner)


def is_locked(
    repo: str,
    target: str,
    *,
    label: str = DEFAULT_LABEL,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    runner: GhRunner | None = None,
) -> bool:
    """Return True iff a fresh lock is currently held on the target."""
    run = runner or _default_runner
    labels = _list_labels(repo, target, run)
    return label in labels and not _lock_is_stale(labels, ttl_seconds)


# ---------------------------------------------------------------------------
# Process-local fake for tests.
# ---------------------------------------------------------------------------


class InMemoryGh:
    """Drop-in fake for the ``runner`` argument used by all helpers in tests.

    The autonomous-loop tests do not have a real GitHub API to call against,
    so the lock module is parametrized on the gh runner. The fake stores the
    label set per target and answers the small subset of ``gh issue view`` /
    ``gh issue edit`` commands the lock uses.
    """

    def __init__(self) -> None:
        self.labels: dict[str, set[str]] = {}

    def _key(self, sub: str, number: str) -> str:
        return f"{sub}:{number}"

    def __call__(self, args: list[str]) -> "subprocess.CompletedProcess[str]":
        # args[0] is "issue" or "pr"; args[1] is the subcommand.
        if len(args) < 2:
            return subprocess.CompletedProcess(args, 2, "", "bad args")
        sub, command = args[0], args[1]
        if command == "view":
            number = args[2]
            key = self._key(sub, number)
            payload = {"labels": [{"name": name} for name in sorted(self.labels.get(key, set()))]}
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if command == "edit":
            number = args[2]
            key = self._key(sub, number)
            current = self.labels.setdefault(key, set())
            if "--add-label" in args:
                idx = args.index("--add-label")
                current.add(args[idx + 1])
            if "--remove-label" in args:
                idx = args.index("--remove-label")
                current.discard(args[idx + 1])
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 2, "", f"unknown command {command!r}")


__all__ = [
    "DEFAULT_LABEL",
    "DEFAULT_TTL_SECONDS",
    "InMemoryGh",
    "LockState",
    "acquire",
    "held",
    "is_locked",
    "release",
    "release_stale",
]
