"""Data models for the next-prompt scheduler.

This module is the stable import location for scheduler data structures. During
incremental refactoring it re-exports the existing implementations from
`next_prompt_legacy`; follow-up PRs can move the concrete definitions here
without changing callers.
"""

from __future__ import annotations

from simulation.tools.next_prompt_legacy import MarkdownDoc, RepoState

__all__ = ["MarkdownDoc", "RepoState"]
