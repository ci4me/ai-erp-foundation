"""Weekly cost rollup across persona scorecards.

Reads every ``simulation/scorecards/<persona>.json``, sums spend over the
last 7 days, and writes a Markdown report (``rollup.md``) suitable for
posting as a comment on the cost-tracking issue.

Exit code is always 0; whether the run *fails* on over-budget is the
workflow's job (it inspects the ``over_budget`` GitHub output we emit).

Invoked by ``.github/workflows/cost-telemetry.yml`` weekly and on demand.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[1]
_SCORECARDS_DIR = _ROOT / "simulation" / "scorecards"

_SECONDS_PER_DAY = 86_400
_ROLLING_WINDOW_DAYS = 7


def _parse_iso(ts: str) -> float | None:
    """Parse an ISO-8601 ``Z`` timestamp into epoch seconds; return None on failure.

    Uses ``calendar.timegm`` (NOT ``time.mktime``) because ``mktime`` treats
    the parsed ``struct_time`` as local time, which silently drifts the
    7-day window on non-UTC runners by the TZ offset. Caught by Theo on
    PR #20 review.
    """
    try:
        return float(calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, TypeError):
        return None


def _within_window(ts: str | None, now: float, window_days: int) -> bool:
    if not ts:
        return False
    epoch = _parse_iso(ts)
    if epoch is None:
        return False
    return (now - epoch) <= (window_days * _SECONDS_PER_DAY)


def _load_scorecards() -> list[dict[str, Any]]:
    """Return parsed contents of every ``<persona>.json`` scorecard."""
    if not _SCORECARDS_DIR.is_dir():
        return []
    scorecards: list[dict[str, Any]] = []
    for path in sorted(_SCORECARDS_DIR.glob("*.json")):
        try:
            scorecards.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: could not parse {path}: {exc}", file=sys.stderr)
    return scorecards


def _aggregate(scorecards: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """Roll spend up by persona, by scenario, and total within the window."""
    per_persona: dict[str, float] = {}
    per_scenario: dict[str, float] = {}
    total = 0.0
    runs = 0

    for card in scorecards:
        persona_id = card.get("persona_id", "<unknown>")
        for scenario_id, entry in card.get("scenarios", {}).items():
            if not _within_window(entry.get("last_run"), now, _ROLLING_WINDOW_DAYS):
                continue
            cost = float(entry.get("cost_usd", 0.0))
            per_persona[persona_id] = per_persona.get(persona_id, 0.0) + cost
            per_scenario[scenario_id] = per_scenario.get(scenario_id, 0.0) + cost
            total += cost
            runs += 1

    return {
        "per_persona": per_persona,
        "per_scenario": per_scenario,
        "total_usd": total,
        "runs": runs,
    }


def _format_markdown(rollup: dict[str, Any], budget: float, over: bool) -> str:
    """Render the rollup as a Markdown comment body."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    status = "🚨 **OVER BUDGET**" if over else "✅ within budget"
    lines: list[str] = [
        f"## Cost Telemetry — weekly rollup ({timestamp})",
        "",
        f"**Window:** last {_ROLLING_WINDOW_DAYS} days  ",
        f"**Total spend:** ${rollup['total_usd']:.4f}  ",
        f"**Budget:** ${budget:.2f}  ",
        f"**Runs:** {rollup['runs']}  ",
        f"**Status:** {status}",
        "",
    ]

    if rollup["per_persona"]:
        lines.append("### Per persona")
        lines.append("")
        lines.append("| Persona | Spend (USD) |")
        lines.append("| --- | --- |")
        for persona_id, cost in sorted(rollup["per_persona"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{persona_id}` | ${cost:.4f} |")
        lines.append("")

    if rollup["per_scenario"]:
        lines.append("### Per scenario")
        lines.append("")
        lines.append("| Scenario | Spend (USD) |")
        lines.append("| --- | --- |")
        for scenario_id, cost in sorted(rollup["per_scenario"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{scenario_id}` | ${cost:.4f} |")
        lines.append("")

    if not rollup["per_persona"] and not rollup["per_scenario"]:
        lines.append(
            "_No scorecards within the rolling window. Live mode probably "
            "hasn't run yet (configure `ANTHROPIC_API_KEY` to enable it)._"
        )

    lines.append("")
    lines.append("_Posted by `Cost Telemetry` workflow._")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=50.0, help="Weekly USD budget ceiling")
    parser.add_argument("--output", type=Path, default=Path("rollup.md"))
    args = parser.parse_args()

    now = time.time()
    scorecards = _load_scorecards()
    rollup = _aggregate(scorecards, now)
    over_budget = rollup["total_usd"] > args.budget
    args.output.write_text(_format_markdown(rollup, args.budget, over_budget))

    # Emit GitHub Actions output for the workflow to gate on.
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as fh:
            fh.write(f"over_budget={'true' if over_budget else 'false'}\n")
            fh.write(f"total_usd={rollup['total_usd']:.4f}\n")
            fh.write(f"runs={rollup['runs']}\n")

    print(args.output.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
