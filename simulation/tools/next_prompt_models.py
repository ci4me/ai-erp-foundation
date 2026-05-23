"""Data models for the next-prompt scheduler.

Stable import location for scheduler data structures. During the incremental
split, this module re-exports the current implementations from next_prompt_legacy.
"""

from __future__ import annotations

from simulation.tools.next_prompt_legacy import MarkdownDoc, RepoState

__all__ = ["MarkdownDoc", "RepoState"]
