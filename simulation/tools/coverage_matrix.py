"""Persona × Scenario coverage analyzer.

Reads every ``simulation/scorecards/*.json`` and computes:

- Per persona: how many scenarios it ran, total flaws it must-catch,
  flaws actually caught, hallucinations emitted, cumulative cost.
- Per scenario: which personas activated, which planted flaws were caught
  by ≥ 1 persona, which were missed by all (the FAILURE-MODE catches).
- Per persona: **unique catches** — flaws this persona alone caught that
  no other persona for the same scenario named. The MVP signal.

Outputs Markdown to stdout (or ``--output FILE``) and an optional JSON
sidecar for further processing.

Identifies:

- **Dead personas** — never caught a unique flaw across any scenario.
  Candidates for Cora's demote-to-observer list (Theme C audit doc).
- **MVP personas** — caught ≥ 1 unique flaw the rest of the squad missed.
- **Hallucination offenders** — personas with > 0 hallucinations in any
  scenario. Need a prompt review.

Usage
-----

::

    python -m simulation.tools.coverage_matrix
    python -m simulation.tools.coverage_matrix --output coverage.md --json coverage.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[2]
_SCORECARDS_DIR = _ROOT / "simulation" / "scorecards"


def load_scorecards() -> list[dict[str, Any]]:
    if not _SCORECARDS_DIR.is_dir():
        return []
    scorecards = []
    for path in sorted(_SCORECARDS_DIR.glob("*.json")):
        try:
            scorecards.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: skip {path}: {exc}", file=sys.stderr)
    return scorecards


def compute_matrix(scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the persona × scenario coverage data structure."""
    # persona_id -> scenario_id -> {flaws_caught, flaws_missed, hallucinations, cost}
    per_persona_scenario: dict[str, dict[str, dict]] = defaultdict(dict)
    # scenario_id -> persona_id -> [caught flaws]
    per_scenario_persona_catches: dict[str, dict[str, list[str]]] = defaultdict(dict)

    for card in scorecards:
        persona_id = card.get("persona_id", "<unknown>")
        for scenario_id, entry in card.get("scenarios", {}).items():
            per_persona_scenario[persona_id][scenario_id] = {
                "verdict_matched": entry.get("verdict_matched"),
                "flaws_must_catch": entry.get("flaws_must_catch", []),
                "flaws_caught": entry.get("flaws_caught", []),
                "flaws_missed": entry.get("flaws_missed", []),
                "hallucinations": entry.get("hallucinations", []),
                "cost_usd": entry.get("cost_usd", 0.0),
                "model": entry.get("model", "<unknown>"),
            }
            per_scenario_persona_catches[scenario_id][persona_id] = entry.get("flaws_caught", [])

    # Unique catches: persona caught a flaw nobody else for the same scenario named
    unique_catches: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for scenario_id, persona_catches in per_scenario_persona_catches.items():
        all_caught_count: dict[str, int] = defaultdict(int)
        for caught in persona_catches.values():
            for flaw in caught:
                all_caught_count[flaw] += 1
        for persona_id, caught in persona_catches.items():
            for flaw in caught:
                if all_caught_count[flaw] == 1:
                    unique_catches[persona_id].append((scenario_id, flaw))

    return {
        "per_persona_scenario": dict(per_persona_scenario),
        "per_scenario_persona_catches": dict(per_scenario_persona_catches),
        "unique_catches": dict(unique_catches),
    }


def classify_personas(matrix: dict[str, Any]) -> dict[str, list[str]]:
    """Bucket personas into MVPs, dead, hallucinators."""
    mvps: list[str] = []
    dead: list[str] = []
    hallucinators: list[str] = []

    for persona_id, scenarios in matrix["per_persona_scenario"].items():
        if matrix["unique_catches"].get(persona_id):
            mvps.append(persona_id)
        else:
            dead.append(persona_id)
        for entry in scenarios.values():
            if entry.get("hallucinations"):
                if persona_id not in hallucinators:
                    hallucinators.append(persona_id)

    return {"mvps": sorted(mvps), "dead": sorted(dead), "hallucinators": sorted(hallucinators)}


def render_markdown(matrix: dict[str, Any], classification: dict[str, list[str]]) -> str:
    lines: list[str] = ["# Persona × Scenario coverage matrix", ""]

    if not matrix["per_persona_scenario"]:
        lines.append("_No scorecards found. Run live-mode regression first to generate data._")
        return "\n".join(lines) + "\n"

    lines += ["## Per-persona summary", "",
              "| Persona | Scenarios | Must-catch | Caught | Missed | Hallucinations | Cost (USD) | Unique catches |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for persona_id in sorted(matrix["per_persona_scenario"].keys()):
        scenarios = matrix["per_persona_scenario"][persona_id]
        n_scenarios = len(scenarios)
        must_catch_total = sum(len(s["flaws_must_catch"]) for s in scenarios.values())
        caught_total = sum(len(s["flaws_caught"]) for s in scenarios.values())
        missed_total = sum(len(s["flaws_missed"]) for s in scenarios.values())
        halls_total = sum(len(s["hallucinations"]) for s in scenarios.values())
        cost_total = sum(s["cost_usd"] for s in scenarios.values())
        uniques = len(matrix["unique_catches"].get(persona_id, []))
        lines.append(
            f"| `{persona_id}` | {n_scenarios} | {must_catch_total} | "
            f"{caught_total} | {missed_total} | {halls_total} | "
            f"${cost_total:.4f} | **{uniques}** |"
        )
    lines.append("")

    lines += ["## Classification", ""]
    if classification["mvps"]:
        lines += ["### 🏆 MVPs (≥ 1 unique catch)", ""]
        for persona_id in classification["mvps"]:
            uniques = matrix["unique_catches"][persona_id]
            lines.append(f"- `{persona_id}` — unique catches: " +
                         ", ".join(f"{s}/{f}" for s, f in uniques))
        lines.append("")
    if classification["dead"]:
        lines += ["### 💀 Dead personas (no unique catches yet)", "",
                  "Candidates for Cora's demote-to-observer list.", ""]
        for persona_id in classification["dead"]:
            lines.append(f"- `{persona_id}`")
        lines.append("")
    if classification["hallucinators"]:
        lines += ["### 🚨 Hallucination offenders", "",
                  "Personas with > 0 backtick-quoted refs not in diff. Prompt-review.", ""]
        for persona_id in classification["hallucinators"]:
            lines.append(f"- `{persona_id}`")
        lines.append("")

    lines += ["## Per-scenario flaw coverage", ""]
    for scenario_id in sorted(matrix["per_scenario_persona_catches"].keys()):
        lines.append(f"### `{scenario_id}`")
        persona_catches = matrix["per_scenario_persona_catches"][scenario_id]
        all_flaws: set[str] = set()
        for caught in persona_catches.values():
            all_flaws.update(caught)
        for persona_id in sorted(persona_catches.keys()):
            caught = persona_catches[persona_id]
            lines.append(f"- `{persona_id}`: {', '.join(sorted(caught)) or '(none)'}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None,
                        help="Write Markdown to this file (default: stdout).")
    parser.add_argument("--json", type=Path, default=None,
                        help="Also dump the raw matrix as JSON to this path.")
    args = parser.parse_args()

    scorecards = load_scorecards()
    matrix = compute_matrix(scorecards)
    classification = classify_personas(matrix)
    markdown = render_markdown(matrix, classification)

    if args.output:
        args.output.write_text(markdown)
        print(f"wrote {len(markdown)} chars to {args.output}", file=sys.stderr)
    else:
        print(markdown)

    if args.json:
        args.json.write_text(json.dumps(
            {"matrix": matrix, "classification": classification},
            indent=2, sort_keys=True, default=list,
        ))
        print(f"wrote JSON to {args.json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
