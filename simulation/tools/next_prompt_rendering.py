"""Prompt rendering facade for the next-prompt scheduler."""

from __future__ import annotations

from simulation.tools.next_prompt_legacy import (
    render_prompt,
    _common_variables,
    _action_variables,
    _review_variables,
    _merge_gate_variables,
    _address_changes_variables,
    _issue_variables,
    _issue_lifecycle_variables,
    _milestone_variables,
    _discussion_variables,
    _generic_action_variables,
    _status_persona_variables,
    _render_template,
)

__all__ = [
    "render_prompt",
    "_common_variables",
    "_action_variables",
    "_review_variables",
    "_merge_gate_variables",
    "_address_changes_variables",
    "_issue_variables",
    "_issue_lifecycle_variables",
    "_milestone_variables",
    "_discussion_variables",
    "_generic_action_variables",
    "_status_persona_variables",
    "_render_template",
]
