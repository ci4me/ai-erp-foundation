"""Simulation orchestrator.

Reads every YAML scenario under ``simulation/scenarios/``, validates it
against ``_schema.yml``, then either:

* **dry-run mode** — prints the planned persona invocations and exits 0.
* **live mode** — dispatches each persona via the Anthropic API,
  asserts the persona's verdict matches ``expected_verdict`` and that
  every flaw in ``must_catch`` is named in the persona's response;
  exits non-zero on any failure.

Mode selection
--------------

* ``--mode dry-run`` forces dry-run regardless of environment.
* ``--mode live`` requires ``ANTHROPIC_API_KEY``; errors if unset.
* ``--mode auto`` (default) picks ``live`` when the env var is set,
  otherwise falls back to dry-run.

Exit codes
----------

* ``0`` — all scenarios passed (or dry-run validated structure).
* ``1`` — at least one scenario failed pass-criteria.
* ``2`` — scenario YAML invalid against schema.
* ``3`` — environment / configuration error (missing API key in live mode, etc.).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML not installed. Run: pip install -r simulation/requirements.txt", file=sys.stderr)
    sys.exit(3)

try:
    from jsonschema import Draft202012Validator, ValidationError
except ImportError:  # pragma: no cover
    print("ERROR: jsonschema not installed. Run: pip install -r simulation/requirements.txt", file=sys.stderr)
    sys.exit(3)


ROOT = Path(__file__).resolve().parent
SCENARIOS_DIR = ROOT / "scenarios"
PROMPTS_DIR = ROOT.parent / ".github" / "agent-prompts"
SCHEMA_PATH = SCENARIOS_DIR / "_schema.yml"


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome of evaluating one scenario."""

    scenario_id: str
    passed: bool
    failures: tuple[str, ...]
    summary: str


def load_schema() -> dict[str, Any]:
    """Read the scenario JSON schema (stored as YAML for editor friendliness)."""
    with SCHEMA_PATH.open() as fh:
        return yaml.safe_load(fh)


def discover_scenarios() -> list[Path]:
    """Return every YAML scenario file (excluding the schema itself)."""
    return sorted(p for p in SCENARIOS_DIR.glob("*.yml") if p.name != "_schema.yml")


def discover_personas() -> set[str]:
    """Return the set of persona slugs that have a prompt file."""
    if not PROMPTS_DIR.is_dir():
        return set()
    return {p.stem for p in PROMPTS_DIR.glob("*.md") if not p.stem.startswith("_") and p.stem != "README"}


def validate_scenario(scenario: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Return a list of validation error messages (empty when valid)."""
    validator = Draft202012Validator(schema)
    return [f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in validator.iter_errors(scenario)]


def check_persona_references(scenario: dict[str, Any], available_personas: set[str]) -> list[str]:
    """Verify every persona referenced by the scenario actually has a prompt file."""
    missing: list[str] = []
    for persona_spec in scenario.get("personas", []):
        persona_id = persona_spec.get("id")
        if persona_id and persona_id not in available_personas:
            missing.append(persona_id)
    return missing


def _scenario_warning(scenario: dict[str, Any]) -> str | None:
    """Return a warning string for non-active scenarios, or ``None``.

    Implements Theo's retirement-policy concern from PR #10: scenarios with
    ``status: deprecated|retired`` still execute, but the harness must surface
    that fact so stale evaluation cases don't rot silently.
    """
    status = scenario.get("status", "active")
    if status == "active":
        return None
    return f"WARNING: scenario {scenario.get('id', '<no id>')} status={status!r} — still executing but flagged for retirement"


def run_dry(scenarios: list[Path], schema: dict[str, Any], personas: set[str]) -> list[ScenarioResult]:
    """Validate scenarios and report what would run, without API calls."""
    results: list[ScenarioResult] = []
    for path in scenarios:
        with path.open() as fh:
            scenario = yaml.safe_load(fh)
        scenario_id = scenario.get("id", path.stem)
        failures: list[str] = []
        for msg in validate_scenario(scenario, schema):
            failures.append(f"schema: {msg}")
        for missing in check_persona_references(scenario, personas):
            failures.append(f"persona '{missing}' referenced but no prompt file at .github/agent-prompts/{missing}.md")
        warning = _scenario_warning(scenario)
        if warning is not None:
            print(warning, file=sys.stderr)
        invocations = len(scenario.get("personas", []))
        summary = f"{scenario_id}: would invoke {invocations} persona(s) — {[p['id'] for p in scenario.get('personas', [])]}"
        results.append(ScenarioResult(scenario_id, not failures, tuple(failures), summary))
    return results


def run_live(scenarios: list[Path], schema: dict[str, Any], personas: set[str]) -> list[ScenarioResult]:
    """Dispatch each scenario's personas via the Anthropic API and assert verdicts.

    Delegates to ``simulation._live`` (separate module so this orchestrator
    stays small). Closes issue #11 — the behavioral regression gate Prism's
    BLOCK demanded.

    Cost ceiling resolution order (per Iris's PR #17 review):
      1. ``MAX_COST_USD`` environment variable (set by the workflow).
      2. Fallback to ``_live._DEFAULT_MAX_COST_PER_SCENARIO_USD``.
    """
    structure_results = run_dry(scenarios, schema, personas)
    if any(not r.passed for r in structure_results):
        return structure_results  # do not waste API tokens on broken scenarios

    from simulation import _live  # late import — anthropic SDK only needed in live mode

    ceiling = _live._DEFAULT_MAX_COST_PER_SCENARIO_USD
    raw_env = os.environ.get("MAX_COST_USD", "").strip()
    if raw_env:
        try:
            ceiling = float(raw_env)
        except ValueError:
            print(f"WARNING: MAX_COST_USD={raw_env!r} not a float, using default {ceiling}", file=sys.stderr)

    live_results = _live.run(scenarios, max_cost_per_scenario_usd=ceiling)
    return [
        ScenarioResult(
            scenario_id=live_result.scenario_id,
            passed=live_result.passed,
            failures=tuple(live_result.failure_reasons),
            summary=(
                f"{live_result.scenario_id}: {len(live_result.personas)} persona(s), "
                f"${live_result.total_cost_usd:.4f}, "
                f"{'PASS' if live_result.passed else 'FAIL'}"
            ),
        )
        for live_result in live_results
    ]


def report(results: list[ScenarioResult], mode: str) -> int:
    """Pretty-print results to stdout and return the exit code."""
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print()
    print(f"=== Prompt regression report — mode={mode} ===")
    print()
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.summary}")
        for failure in r.failures:
            print(f"          ✗ {failure}")
    print()
    print(f"  {passed}/{total} scenario(s) passed.")
    return 0 if passed == total else 1


def main() -> int:
    """Entry point used by the CI workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("auto", "dry-run", "live"), default="auto")
    args = parser.parse_args()

    if args.mode == "auto":
        mode = "live" if os.environ.get("ANTHROPIC_API_KEY") else "dry-run"
    else:
        mode = args.mode

    if mode == "live" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: --mode live requires ANTHROPIC_API_KEY environment variable.", file=sys.stderr)
        return 3

    if not SCHEMA_PATH.is_file():
        print(f"ERROR: scenario schema missing at {SCHEMA_PATH}", file=sys.stderr)
        return 2

    schema = load_schema()
    scenarios = discover_scenarios()
    personas = discover_personas()

    print(f"Discovered {len(scenarios)} scenario(s) and {len(personas)} persona prompt(s).")
    print(f"Mode: {mode}")
    if not scenarios:
        print("No scenarios to run. Add YAML files under simulation/scenarios/.")
        return 0

    if mode == "dry-run":
        results = run_dry(scenarios, schema, personas)
    else:
        results = run_live(scenarios, schema, personas)

    return report(results, mode)


if __name__ == "__main__":
    sys.exit(main())
