"""Cached GitHub CLI shim used by the autonomous loop.

The autonomous loop reads the same ``gh issue list`` / ``gh pr view`` calls
many times within a single tick (selectors, validators, post-action
verification). Each call costs ~150 ms and counts against the GitHub
rate limit. This module wraps ``gh`` with a short-TTL on-disk cache so
back-to-back reads return memoized output without touching the network.

Backends, in order of preference:

1. ``requests_cache`` — when the package is installed we install a
   global SQLite-backed cache at ``~/.cache/gh_cache`` with a 10-second
   TTL. The cache only catches HTTP-level reads; ``gh`` itself doesn't
   make HTTP through ``requests``, so we *also* maintain an in-memory
   subprocess cache below for the common path.
2. In-memory subprocess cache — :class:`GhClient` keeps a dict of
   ``(cmd_args) → (timestamp, stdout)`` and serves matches within the
   TTL window.

Read commands (``view``, ``list``, ``api``, ``status``) are cached.
Mutating commands (``edit``, ``comment``, ``create``, ``close``,
``merge``, ``review``) bypass the cache and invalidate it for the
target object.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

CACHE_PATH = Path(os.environ.get("GH_CACHE_PATH") or Path.home() / ".cache" / "gh_cache")
DEFAULT_TTL_SECONDS = 10
READ_VERBS = frozenset({"view", "list", "api", "status", "search"})
MUTATION_VERBS = frozenset({"edit", "comment", "create", "close", "merge", "review", "delete"})

try:
    import requests_cache as _rc  # type: ignore[import-not-found]

    CACHE_PATH.mkdir(parents=True, exist_ok=True)
    _rc.install_cache(str(CACHE_PATH / "gh_cache"), expire_after=DEFAULT_TTL_SECONDS)
    _REQUESTS_CACHE_INSTALLED = True
except ImportError:  # pragma: no cover — optional dependency
    _REQUESTS_CACHE_INSTALLED = False


class GhClient:
    """Subprocess wrapper around the ``gh`` CLI with a TTL cache for reads."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if not shutil.which("gh"):
            raise RuntimeError("`gh` CLI is required for GhClient")
        self.ttl_seconds = ttl_seconds
        self._cache: dict[tuple[str, ...], tuple[float, str]] = {}

    def _verb(self, args: Sequence[str]) -> str:
        # gh sub-command shapes: `gh <area> <verb> [args...]` — area is the
        # noun (issue/pr/api/etc) and verb is the action.
        return args[1] if len(args) > 1 else ""

    def _invalidate(self, args: Sequence[str]) -> None:
        # On mutation we drop any cached entries that mention the same
        # area + number (best-effort string match keeps this simple).
        target = ""
        for token in args:
            if token.isdigit():
                target = token
                break
        keys = list(self._cache)
        for key in keys:
            if target and target in key:
                del self._cache[key]
            elif args[:2] == key[:2]:
                del self._cache[key]

    def __call__(self, args: Sequence[str]) -> str:
        verb = self._verb(args)
        key = tuple(args)
        if verb in READ_VERBS:
            entry = self._cache.get(key)
            if entry is not None and time.time() - entry[0] <= self.ttl_seconds:
                return entry[1]
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        out = result.stdout or ""
        if verb in READ_VERBS and result.returncode == 0:
            self._cache[key] = (time.time(), out)
        if verb in MUTATION_VERBS:
            self._invalidate(args)
        return out


_DEFAULT_CLIENT: GhClient | None = None


def get_default_client() -> GhClient:
    """Return a process-wide :class:`GhClient` instance."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = GhClient()
    return _DEFAULT_CLIENT


def cached_gh(args: Sequence[str]) -> str:
    """One-shot convenience wrapper around the default client."""
    return get_default_client()(args)


__all__ = [
    "CACHE_PATH",
    "DEFAULT_TTL_SECONDS",
    "GhClient",
    "cached_gh",
    "get_default_client",
]
