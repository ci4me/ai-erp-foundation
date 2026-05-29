"""Registry of machine-readable autonomous-loop markers.

The autonomous loop uses GitHub comments, reviews, and discussions as its
persistent state store. Natural-language prose is not safe enough for this job:
an agent can say "looks good" in many ways, but the next iteration needs one
stable token to parse. This module loads `.github/action-templates/markers.yml`
and exposes small helpers for validators, tests, and documentation generators.

Design rule
-----------
Every catalog action that posts to GitHub has a primary marker. The marker is
not merely decorative; it is the state transition that tells `next_prompt.py`
what happened and whether the loop should continue, stop, merge, close, or ask
for another persona.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - repo requirements include PyYAML.
    yaml = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKER_REGISTRY_PATH = REPO_ROOT / ".github" / "action-templates" / "markers.yml"


@dataclass(frozen=True)
class MarkerSpec:
    """One action's declared state marker contract."""

    action_id: str
    marker: str
    values: tuple[str, ...]
    regex: str
    terminal: bool
    meaning: str

    def matches(self, body: str) -> bool:
        """Return True when `body` contains this action's required marker."""
        return re.search(self.regex, body) is not None

    def example(self) -> str:
        """Return a conservative example marker line for prompts/docs."""
        value = self.values[0] if self.values else "POSTED"
        return f"{self.marker}: {value}"


def load_marker_specs() -> dict[str, MarkerSpec]:
    """Load and validate marker specs keyed by action id."""
    if yaml is None:
        raise RuntimeError("PyYAML is required to load marker registry")
    data = yaml.safe_load(MARKER_REGISTRY_PATH.read_text()) or {}
    raw_markers = data.get("markers") or {}
    if not isinstance(raw_markers, dict):
        raise RuntimeError("markers.yml must contain a mapping at `markers`")

    specs: dict[str, MarkerSpec] = {}
    for action_id, raw in raw_markers.items():
        if not isinstance(raw, dict):
            raise RuntimeError(f"marker spec for {action_id} must be a mapping")
        marker = str(raw.get("marker") or "").strip()
        regex = str(raw.get("regex") or "").strip()
        if not marker or not regex:
            raise RuntimeError(f"marker spec for {action_id} needs marker and regex")
        values = tuple(str(value) for value in (raw.get("values") or []))
        # Compile early so CI fails before a broken regex reaches a prompt.
        re.compile(regex)
        specs[str(action_id)] = MarkerSpec(
            action_id=str(action_id),
            marker=marker,
            values=values,
            regex=regex,
            terminal=bool(raw.get("terminal", False)),
            meaning=str(raw.get("meaning") or ""),
        )
    return specs


def get_marker_spec(action_id: str) -> MarkerSpec | None:
    """Return the marker spec for an action, or None if action is unknown."""
    return load_marker_specs().get(action_id)


def marker_names() -> tuple[str, ...]:
    """Return all marker prefixes used to detect agent-shaped outputs."""
    names = sorted({spec.marker + ":" for spec in load_marker_specs().values()})
    return tuple(names)


def _load_section(section: str) -> dict[str, Any]:
    """Load a non-action marker section (``request_markers``/``collaboration_markers``).

    These sections live alongside ``markers:`` but are deliberately excluded from
    the action<->marker registry, so they are read directly here.
    """
    if yaml is None:
        raise RuntimeError("PyYAML is required to load marker registry")
    data = yaml.safe_load(MARKER_REGISTRY_PATH.read_text()) or {}
    raw = data.get(section) or {}
    return raw if isinstance(raw, dict) else {}


def _section_prefixes(section: str) -> tuple[str, ...]:
    raw = _load_section(section)
    return tuple(
        sorted(f"{(spec or {}).get('marker', name)}:" for name, spec in raw.items())
    )


def request_marker_names() -> tuple[str, ...]:
    """Marker prefixes for persona-request markers (e.g. ``REQUEST-REPLY-FROM:``)."""
    return _section_prefixes("request_markers")


def collaboration_marker_names() -> tuple[str, ...]:
    """Marker prefixes for collaboration markers (e.g. ``ARGUMENT:``, ``RESOLUTION:``)."""
    return _section_prefixes("collaboration_markers")


def all_marker_prefixes() -> tuple[str, ...]:
    """Every recognized marker prefix: action + request + collaboration."""
    return tuple(
        sorted(set(marker_names()) | set(request_marker_names()) | set(collaboration_marker_names()))
    )


def infer_actions_from_body(body: str) -> list[str]:
    """Return all action ids whose marker regex matches the supplied body."""
    return [action_id for action_id, spec in load_marker_specs().items() if spec.matches(body)]


def validate_catalog_coverage(action_ids: set[str]) -> list[str]:
    """Ensure every catalog action has exactly one marker contract."""
    errors: list[str] = []
    specs = load_marker_specs()
    missing = sorted(action_ids - set(specs))
    extra = sorted(set(specs) - action_ids)
    for action_id in missing:
        errors.append(f"action missing marker spec: {action_id}")
    for action_id in extra:
        errors.append(f"marker spec references unknown action: {action_id}")
    return errors


def format_marker_table() -> str:
    """Render a Markdown table documenting the registry."""
    rows = ["| Action | Marker | Values | Terminal | Meaning |", "| --- | --- | --- | --- | --- |"]
    for action_id, spec in sorted(load_marker_specs().items()):
        values = ", ".join(spec.values) if spec.values else "free-form"
        terminal = "yes" if spec.terminal else "no"
        meaning = spec.meaning.replace("|", "\\|")
        rows.append(f"| `{action_id}` | `{spec.marker}:` | {values} | {terminal} | {meaning} |")
    return "\n".join(rows)
