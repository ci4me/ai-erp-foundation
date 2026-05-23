"""Action-bundle helpers for next_prompt.

This module keeps the bundle rules small, deterministic, and easy to test before
`next_prompt.py` wires them into its priority resolver. The scheduler still owns
GitHub state discovery and template rendering; these helpers answer three narrow
questions:

1. Can an additional action run in the same prompt as the primary action?
2. Does the action payload fit inside a self-contained prompt?
3. How should a selected set of actions be summarized for a cold agent?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_INLINE_CHAR_LIMIT = 20_000

# Actions here intentionally get a dedicated prompt because they change lifecycle
# state, depend on state just produced by an earlier action, or are terminal.
TERMINAL_OR_LOCKING_ACTIONS = frozenset(
    {
        "accept_pr",
        "address_changes_requested",
        "close_discussion",
        "close_issue",
        "close_milestone",
        "merge_gate",
        "merge_pr",
        "migrate_persona",
        "reject_pr",
        "skip",
        "post_status_and_exit",
    }
)

# These actions are usually independent comments, triage, or follow-up creation.
# They may be bundled when the selected persona owns all of them and their target
# objects do not overlap.
INDEPENDENT_ACTIONS = frozenset(
    {
        "comment_discussion",
        "create_issue",
        "decision_record",
        "generate_ideas",
        "knowledge_update",
        "open_followup_issue",
        "prompt_improvement",
        "promote_idea",
        "request_review",
        "review_pr",
        "run_audit",
        "run_prompt_regression",
        "security_audit",
        "triage_issue",
        "verify_agent_action",
    }
)


@dataclass(frozen=True)
class ActionSelection:
    """One legal action selected by the autonomous scheduler."""

    action_id: str
    persona_id: str
    context: dict[str, Any] = field(default_factory=dict)
    payload: str = ""
    summary: str = ""

    @property
    def object_key(self) -> str:
        """Return a stable object key used to avoid same-object bundles."""
        for key in ("pr", "issue", "discussion", "milestone"):
            value = self.context.get(key)
            if isinstance(value, dict) and value.get("number") is not None:
                return f"{key}:{value['number']}"
        for key in ("pr_number", "issue_number", "discussion_number", "milestone_number"):
            value = self.context.get(key)
            if value is not None:
                return f"{key.removesuffix('_number')}:{value}"
        return f"action:{self.action_id}:{id(self.context)}"


@dataclass(frozen=True)
class ActionBundle:
    """A single-persona bundle of one primary action plus compatible extras."""

    selected_persona: str
    primary_action: ActionSelection
    additional_actions: tuple[ActionSelection, ...] = ()

    @property
    def actions(self) -> tuple[ActionSelection, ...]:
        """Return the execution order for the prompt."""
        return (self.primary_action, *self.additional_actions)

    @property
    def is_multi_action(self) -> bool:
        """Return True when the prompt should render an ACTION BUNDLE."""
        return len(self.actions) > 1


def should_inline_content(payload: str, *, inline_char_limit: int = DEFAULT_INLINE_CHAR_LIMIT) -> bool:
    """Return whether payload is small enough to inline in the prompt."""
    if inline_char_limit <= 0:
        return True
    return len(payload) <= inline_char_limit


def is_terminal_or_locking(action_id: str) -> bool:
    """Return True when an action must run alone."""
    return action_id in TERMINAL_OR_LOCKING_ACTIONS


def is_independent(action_id: str) -> bool:
    """Return True when an action may be considered for bundling."""
    return action_id in INDEPENDENT_ACTIONS


def actions_are_compatible(primary: ActionSelection, candidate: ActionSelection) -> bool:
    """Return True if candidate may run after primary in the same prompt.

    Compatibility is intentionally conservative. A candidate is allowed only when
    it uses the same persona, neither action is terminal/locking, both actions are
    marked independent, and they target different GitHub objects.
    """
    if primary.persona_id != candidate.persona_id:
        return False
    if is_terminal_or_locking(primary.action_id) or is_terminal_or_locking(candidate.action_id):
        return False
    if not is_independent(primary.action_id) or not is_independent(candidate.action_id):
        return False
    return primary.object_key != candidate.object_key


def build_action_bundle(
    primary: ActionSelection,
    candidates: list[ActionSelection],
    *,
    max_additional_actions: int = 2,
) -> ActionBundle:
    """Build a conservative same-persona action bundle.

    The hard caps in the prompt still apply. The default of two additional
    actions prevents one rendered prompt from becoming a hidden batch job.
    """
    compatible: list[ActionSelection] = []
    seen_objects = {primary.object_key}
    for candidate in candidates:
        if len(compatible) >= max_additional_actions:
            break
        if candidate.object_key in seen_objects:
            continue
        if not actions_are_compatible(primary, candidate):
            continue
        compatible.append(candidate)
        seen_objects.add(candidate.object_key)
    return ActionBundle(
        selected_persona=primary.persona_id,
        primary_action=primary,
        additional_actions=tuple(compatible),
    )


def render_bundle_summary(bundle: ActionBundle, *, inline_char_limit: int = DEFAULT_INLINE_CHAR_LIMIT) -> str:
    """Render a compact Markdown summary of a selected action bundle."""
    heading = "ACTION BUNDLE" if bundle.is_multi_action else "ACTION"
    lines = [f"## {heading}", "", f"Persona: `{bundle.selected_persona}`", "", "Execute these tasks in order:"]
    for index, action in enumerate(bundle.actions, start=1):
        inline_status = "inline" if should_inline_content(action.payload, inline_char_limit=inline_char_limit) else "fetch-required"
        summary = action.summary or action.object_key
        lines.append(f"{index}. `{action.action_id}` on `{action.object_key}` - {summary} ({inline_status})")
    lines.extend(
        [
            "",
            "Do not choose the next action yourself.",
            "After posting the required markers, rerun `next_prompt.py` so GitHub state decides the next action.",
        ]
    )
    return "\n".join(lines)
