#!/usr/bin/env python3
"""Dynamic discovery of AI personas from ``.github/agent-prompts/*.md``.

Every persona in this repository is a markdown file whose YAML frontmatter
declares its identity *and* the catalog actions it is allowed to perform, e.g.::

    ---
    id: rhea-release-manager
    name: Rhea
    role: AI Release Manager
    layer: assurance
    model_default: claude-sonnet-4-6
    actions:
      primary: [review_pr, accept_pr, merge_gate, merge_pr, reject_pr]
      support: [re_ratification, close_issue]
    ---

The registry parses every such file and builds two indexes:

1. ``id -> persona`` for direct lookup.
2. ``action -> [persona ids]`` derived from each persona's
   ``actions.primary``/``actions.support`` lists. This makes
   :meth:`PersonaRegistry.get_persona_for_action` *genuinely dynamic*: the
   correct owner of an action is whoever declares it in their frontmatter, not
   a hardcoded table. The hardcoded map only survives as a last-resort fallback
   and as an alias layer for the planner's pseudo-actions (e.g. ``close_pr``,
   which has no catalog entry but maps onto ``reject_pr``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

# Planner pseudo-actions -> the real catalog action that owns the same intent.
# The planner emits coarse verbs ("close this PR"); personas declare fine-grained
# catalog actions. This alias layer bridges the two so discovery stays dynamic.
ACTION_ALIASES: dict[str, str] = {
    "close_pr": "reject_pr",
    "comment_issue": "triage_issue",
    "comment_discussion": "comment_discussion",
    "create_pr": "implement_issue",
    "review_pr": "review_pr",
    "merge_pr": "merge_pr",
    "close_issue": "close_issue",
}

# Absolute last resort if neither the dynamic index nor the alias resolves and
# the registry is somehow empty. Ari is the always-on orchestrator.
DEFAULT_PERSONA_ID = "ari-orchestrator"

DEFAULT_MODEL = "claude-sonnet-4-6"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PersonaRegistry:
    """Reads persona markdown files and resolves action ownership dynamically."""

    def __init__(self, repo_root: str = ".") -> None:
        self.repo_root = Path(repo_root)
        self.prompts_dir = self.repo_root / ".github" / "agent-prompts"
        self._personas: Optional[list[dict[str, Any]]] = None
        self._action_index: Optional[dict[str, list[str]]] = None

    # -- parsing ----------------------------------------------------------

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, Any]:
        """Extract and parse the YAML frontmatter block of a markdown file.

        Returns an empty dict when there is no frontmatter or it fails to parse,
        so a malformed file is skipped rather than crashing discovery.
        """
        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _declared_actions(frontmatter: dict[str, Any]) -> list[str]:
        """Flatten ``actions.primary`` + ``actions.support`` into a unique list."""
        actions = frontmatter.get("actions") or {}
        if not isinstance(actions, dict):
            return []
        ordered: list[str] = []
        for bucket in ("primary", "support"):
            for action in actions.get(bucket) or []:
                if action and action not in ordered:
                    ordered.append(str(action))
        return ordered

    # -- loading ----------------------------------------------------------

    def load_all(self) -> list[dict[str, Any]]:
        """Load (and memoize) every valid persona under the prompts dir.

        A file is a valid persona iff its frontmatter contains an ``id``. The
        roster file, README, and ``_preamble.md`` are naturally skipped because
        they have no ``id`` frontmatter key.
        """
        if self._personas is not None:
            return self._personas

        personas: list[dict[str, Any]] = []
        if self.prompts_dir.exists():
            for md_file in sorted(self.prompts_dir.glob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                fm = self._parse_frontmatter(content)
                if not fm.get("id"):
                    continue
                personas.append(
                    {
                        "id": fm["id"],
                        "name": fm.get("name", fm["id"]),
                        "layer": fm.get("layer", "unknown"),
                        "role": fm.get("role", "unknown"),
                        # The real frontmatter uses ``model_default``; tolerate a
                        # plain ``model`` key too for forward compatibility.
                        "model": fm.get("model_default") or fm.get("model") or DEFAULT_MODEL,
                        "actions": self._declared_actions(fm),
                        "file": str(md_file.relative_to(self.repo_root)),
                    }
                )
        self._personas = personas
        return personas

    def _build_action_index(self) -> dict[str, list[str]]:
        """Map each declared catalog action to the personas that own it."""
        if self._action_index is not None:
            return self._action_index
        index: dict[str, list[str]] = {}
        for persona in self.load_all():
            for action in persona["actions"]:
                index.setdefault(action, []).append(persona["id"])
        self._action_index = index
        return index

    # -- lookups ----------------------------------------------------------

    def get_persona(self, persona_id: str) -> Optional[dict[str, Any]]:
        """Return the full persona dict for an id, or None."""
        for persona in self.load_all():
            if persona["id"] == persona_id:
                return persona
        return None

    def get_persona_by_layer(self, layer: str) -> Optional[dict[str, Any]]:
        """Return the first persona in a given layer (e.g. ``assurance``)."""
        for persona in self.load_all():
            if persona["layer"] == layer:
                return persona
        return None

    def get_persona_by_role(self, role: str) -> Optional[dict[str, Any]]:
        """Return the first persona whose role contains ``role`` (case-insensitive)."""
        needle = role.lower()
        for persona in self.load_all():
            if needle in persona["role"].lower():
                return persona
        return None

    def get_persona_for_action(self, action: str) -> str:
        """Resolve the persona id that should perform ``action``.

        Resolution order (first hit wins):

        1. **Dynamic index** — a persona that literally declares ``action`` in
           its frontmatter ``actions`` list.
        2. **Alias** — translate a planner pseudo-action (``close_pr``,
           ``comment_issue``, …) to its catalog equivalent and retry the index.
        3. **Layer heuristic** — review/comment work falls to the assurance
           layer when nothing else matched.
        4. **Default** — the first known persona, or :data:`DEFAULT_PERSONA_ID`.
        """
        index = self._build_action_index()

        if action in index:
            return index[action][0]

        aliased = ACTION_ALIASES.get(action)
        if aliased and aliased in index:
            return index[aliased][0]

        if action in ("review_pr", "comment_issue"):
            assurance = self.get_persona_by_layer("assurance")
            if assurance:
                return assurance["id"]

        personas = self.load_all()
        return personas[0]["id"] if personas else DEFAULT_PERSONA_ID

    def get_model_for_persona(self, persona_id: str) -> str:
        """Return the default model for a persona id (or the global default)."""
        persona = self.get_persona(persona_id)
        return persona["model"] if persona else DEFAULT_MODEL
