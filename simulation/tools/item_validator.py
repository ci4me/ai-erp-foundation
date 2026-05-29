#!/usr/bin/env python3
"""Validity / scope filter for the autonomous loop's inputs.

The planner picks one action across *all* open issues, PRs, and discussions. In
a real (or long-lived sandbox) repo that pool contains junk — spam, duplicates,
malformed items, note-only PRs, and stale backlog — that the loop should
**skip**, not act on. This module decides, deterministically, which items the
planner is even allowed to consider.

Two mechanisms, both opt-in and backward-compatible (a repo using none of these
labels behaves exactly as before):

1. **Skip labels** — an item carrying any of :data:`SKIP_LABELS`
   (``invalid``, ``duplicate``, ``wontfix``, ``spam``, ``on-hold``,
   ``loop:skip``) is removed from the loop's view.
2. **Note-only PRs** — a PR whose changed files are known and contain no
   source-code file is skipped (it cannot be merged as a real change).
3. **Focus mode** — if *any* open item carries :data:`FOCUS_LABEL`
   (``loop:active``), the loop is restricted to *only* the focused items. This
   lets an operator point the team at one feature (e.g. a fresh epic) without
   touching the surrounding backlog.

:func:`filter_state` returns the filtered snapshot plus a transparent list of
``(kind, number, reason)`` for everything skipped, so callers can report it.
"""

from __future__ import annotations

from typing import Any

from simulation.tools.state_fetcher import CODE_EXTENSIONS

# Files that constitute a real, mergeable change beyond source code:
# CI/infrastructure config, build, data, and web assets. A workflow YAML or a
# Terraform/Dockerfile change alters system behavior and must be reviewed — it
# is not a "note". Documentation (``.md``/``.rst``/``.txt``) is intentionally
# *not* here: a docs-only PR stays "note-only" by design (see
# ``test_item_validator.test_note_only_pr_skipped``).
NON_CODE_ACTIONABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env",
        ".sh", ".bash", ".zsh", ".ps1", ".dockerfile", ".tf", ".tfvars",
        ".gradle", ".bazel", ".mk", ".cmake",
        ".html", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
        ".proto", ".graphql", ".xml", ".csv",
    }
)
# A PR touching any file with one of these extensions is a real change.
ACTIONABLE_EXTENSIONS: frozenset[str] = CODE_EXTENSIONS | NON_CODE_ACTIONABLE_EXTENSIONS

# Items with any of these labels are never acted on by the loop.
SKIP_LABELS: frozenset[str] = frozenset(
    {"invalid", "duplicate", "wontfix", "spam", "on-hold", "loop:skip"}
)
# When present on any item, the loop is restricted to items carrying this label.
FOCUS_LABEL = "loop:active"


def _labels(item: dict[str, Any]) -> list[str]:
    return [
        (lbl.get("name", "") if isinstance(lbl, dict) else str(lbl))
        for lbl in (item.get("labels") or [])
    ]


def _is_note_only_pr(item: dict[str, Any]) -> bool:
    """True iff a PR's changed files are known and include no actionable file.

    "Actionable" spans source code *and* CI/config/infra/build/web assets
    (:data:`ACTIONABLE_EXTENSIONS`); only documentation-style files (``.md``,
    ``.rst``, ``.txt``) are treated as notes. When file info is absent
    (``files`` missing/empty) we do not guess — the PR is left in scope so the
    loop can fetch and decide.
    """
    files = item.get("files") or []
    if not files:
        return False
    paths = [f.get("path", "") if isinstance(f, dict) else str(f) for f in files]
    has_actionable = any(p.endswith(ext) for p in paths for ext in ACTIONABLE_EXTENSIONS)
    return not has_actionable


def validate_item(item: dict[str, Any], kind: str) -> tuple[bool, str]:
    """Return ``(is_actionable, reason)`` for one issue / pr / discussion.

    This is the per-item check *without* focus mode (focus is a cross-item
    decision handled in :func:`filter_state`).
    """
    labels = _labels(item)
    for label in labels:
        if label in SKIP_LABELS:
            return False, f"labeled '{label}'"
    if kind == "pr" and _is_note_only_pr(item):
        return False, "note-only PR (no source-code files)"
    return True, "ok"


def filter_state(state: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, Any, str]]]:
    """Filter a state snapshot to the items the loop may act on.

    Returns ``(filtered_state, skipped)`` where ``skipped`` is a list of
    ``(kind, number, reason)``. Non-list keys in ``state`` (e.g. ``repo``) are
    preserved untouched.
    """
    groups = {"prs": "pr", "issues": "issue", "discussions": "discussion"}

    # Focus mode is active if any open item opts in via FOCUS_LABEL.
    focus_active = any(
        FOCUS_LABEL in _labels(item)
        for key in groups
        for item in (state.get(key) or [])
    )

    filtered: dict[str, Any] = dict(state)
    skipped: list[tuple[str, Any, str]] = []

    for key, kind in groups.items():
        kept: list[dict[str, Any]] = []
        for item in state.get(key) or []:
            ok, reason = validate_item(item, kind)
            if not ok:
                skipped.append((kind, item.get("number"), reason))
                continue
            if focus_active and FOCUS_LABEL not in _labels(item):
                skipped.append((kind, item.get("number"), f"outside {FOCUS_LABEL} focus set"))
                continue
            kept.append(item)
        filtered[key] = kept

    return filtered, skipped
