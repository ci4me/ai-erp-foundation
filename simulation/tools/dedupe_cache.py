"""Re-export of :class:`simulation.tools.loop_speedup.DedupeCache`.

The cache lives in ``loop_speedup`` alongside the StallTracker and the
other speed-up helpers — they share state across the orchestrator's
guard chain. Operators who imported it under the standalone name in
the audit spec can keep using ``simulation.tools.dedupe_cache.DedupeCache``.
"""

from __future__ import annotations

from simulation.tools.loop_speedup import DEFAULT_DEDUPE_WINDOW_MIN, DedupeCache

__all__ = ["DEFAULT_DEDUPE_WINDOW_MIN", "DedupeCache"]
