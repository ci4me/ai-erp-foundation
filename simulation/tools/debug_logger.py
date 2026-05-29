#!/usr/bin/env python3
"""Structured debug logging for the autonomous planner.

Every executed (or dry-run) step is written to its own JSON file so a run can be
replayed and audited offline. Files land under::

    logs/YYYY-MM-DD/<run_id>-step-<NNNN>.json

where ``run_id`` is unique per process. Each file mirrors the documented schema::

    {
      "timestamp": "2026-05-29T14:30:00+00:00",
      "run_id": "20260529-143000-123456",
      "mode": "single" | "multi",
      "step_index": 1,
      "persona": "ari-orchestrator",
      "action": "comment_issue",
      "target": {"type": "issue", "number": 140},
      "prompt_body": "full body sent (if applicable)",
      "response_body": null,            # planner is LLM-free; reserved
      "gh_command": "gh issue comment ...",
      "gh_output": "...",
      "success": true,
      "error": null,
      "dry_run": false
    }

This replaces the planner's ad-hoc ``print`` calls. The logger still emits a
single concise console line per step so an operator sees live progress; the full
detail goes to the JSON file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Fields that, when present, are emitted in a stable order at the top of each
# record. Any extra kwargs are appended after these.
_PREFERRED_ORDER = (
    "timestamp",
    "run_id",
    "mode",
    "step_index",
    "persona",
    "action",
    "target",
    "prompt_body",
    "response_body",
    "gh_command",
    "gh_output",
    "success",
    "error",
    "dry_run",
)


class DebugLogger:
    """Writes one JSON file per step and prints a one-line progress summary."""

    def __init__(self, base_dir: str = "logs") -> None:
        self.base_dir = Path(base_dir)
        now = datetime.now(timezone.utc)
        self.current_run_id = now.strftime("%Y%m%d-%H%M%S-%f")
        self.step_counter = 0
        self.mode: Optional[str] = None
        # Materialize today's directory eagerly so the path exists before the
        # first write (and so an empty run still leaves a dated folder).
        self._date_dir(now).mkdir(parents=True, exist_ok=True)

    def _date_dir(self, when: datetime) -> Path:
        return self.base_dir / when.strftime("%Y-%m-%d")

    def set_mode(self, mode: str) -> None:
        """Record the planner mode (single/multi) stamped on every entry."""
        self.mode = mode

    def log(self, **fields: Any) -> Path:
        """Write one step record and print a concise console line.

        Any keyword arguments are stored verbatim. ``timestamp``, ``run_id``,
        ``mode``, and ``step_index`` are injected automatically (callers may
        still override them).

        Returns the path of the written JSON file.
        """
        self.step_counter += 1
        now = datetime.now(timezone.utc)

        entry: dict[str, Any] = {
            "timestamp": now.isoformat(),
            "run_id": self.current_run_id,
            "mode": self.mode,
            "step_index": self.step_counter,
        }
        entry.update(fields)
        ordered = {k: entry[k] for k in _PREFERRED_ORDER if k in entry}
        ordered.update({k: v for k, v in entry.items() if k not in ordered})

        date_dir = self._date_dir(now)
        date_dir.mkdir(parents=True, exist_ok=True)
        path = date_dir / f"{self.current_run_id}-step-{self.step_counter:04d}.json"
        path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

        self._print_line(ordered)
        return path

    @staticmethod
    def _print_line(entry: dict[str, Any]) -> None:
        persona = str(entry.get("persona", "?"))
        action = str(entry.get("action", "?"))
        target = entry.get("target") or {}
        target_str = f"{target.get('type', '')}#{target.get('number', '')}"
        status = "ok" if entry.get("success", True) else "FAIL"
        tag = "dry" if entry.get("dry_run") else "live"
        print(f"📝 [{tag}] {persona:24} | {action:16} | {target_str:14} | {status}")


# Process-global logger so all modules share one run_id and step counter.
_logger: Optional[DebugLogger] = None


def get_logger() -> DebugLogger:
    """Return the process-wide :class:`DebugLogger`, creating it on first use."""
    global _logger
    if _logger is None:
        _logger = DebugLogger()
    return _logger


def reset_logger() -> None:
    """Drop the cached logger (used by tests to force a fresh run_id)."""
    global _logger
    _logger = None
