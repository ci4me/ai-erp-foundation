"""Audit autonomous-loop action and scenario coverage.

This tool is deliberately static: it does not call GitHub. It answers the
operator question, "Can a cold agent execute every action that `next_prompt.py`
may render, and will every action leave a machine-readable marker?"

Run it before changing the catalog, templates, persona prompts, or scenario
catalog. The output is concise enough for CI logs and detailed enough for a
human to find the missing contract.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - repo requirements include PyYAML.
    yaml = None  # type: ignore[assignment]

from simulation.tools import marker_registry, next_prompt


@dataclass(frozen=True)
class CoverageReport:
    """Static coverage result for the autonomous loop."""

    ok: bool
    errors: list[str]
    warnings: list[str]
    actions: list[str]
    scenarios: list[str]
    missing_scenarios: list[str]
    orphan_scenarios: list[str]


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping or return an empty dict when absent."""
    if yaml is None or not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    return loaded if isinstance(loaded, dict) else {}


def _persona_action_owners() -> dict[str, list[str]]:
    """Return action id -> persona ids that mention that action."""
    owners: dict[str, list[str]] = {}
    for persona_id, doc in next_prompt._load_persona_index().items():
        actions = doc.frontmatter.get("actions") or {}
        if not isinstance(actions, dict):
            continue
        for relation in ("primary", "support"):
            for action_id in next_prompt._as_list(actions.get(relation)):
                owners.setdefault(action_id, []).append(f"{persona_id}:{relation}")
    return owners


def audit_coverage() -> CoverageReport:
    """Validate catalog/template/marker/persona/scenario coverage."""
    errors = next_prompt.validate_static_config()
    warnings: list[str] = []
    actions = next_prompt._load_action_catalog()
    action_ids = [str(action.get("id")) for action in actions if action.get("id")]
    owners = _persona_action_owners()

    for action_id in action_ids:
        if action_id not in owners:
            errors.append(f"action has no persona owner: {action_id}")
        spec = marker_registry.get_marker_spec(action_id)
        if spec is None:
            continue
        template_name = next_prompt._template_name_for_action(action_id)
        template_path = next_prompt.ACTION_TEMPLATES_DIR / template_name
        if template_path.exists() and f"{spec.marker}:" not in template_path.read_text():
            errors.append(f"template does not document marker {spec.marker}: for action {action_id}")

    scenario_catalog = next_prompt._scenario_catalog()
    scenario_dir = next_prompt.REPO_ROOT / "simulation" / "scenarios"
    scenario_files = {
        path.stem
        for path in scenario_dir.glob("*.yml")
        if not path.name.startswith("_") and path.name != "catalog.yml"
    }
    missing_scenarios = sorted(set(scenario_catalog) - scenario_files)
    orphan_scenarios = sorted(scenario_files - set(scenario_catalog))
    for scenario_id in missing_scenarios:
        errors.append(f"scenario catalog entry has no file: {scenario_id}.yml")
    for scenario_id in orphan_scenarios:
        warnings.append(f"scenario file is not cataloged: {scenario_id}.yml")

    return CoverageReport(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        actions=action_ids,
        scenarios=scenario_catalog,
        missing_scenarios=missing_scenarios,
        orphan_scenarios=orphan_scenarios,
    )


def format_markdown(report: CoverageReport) -> str:
    """Render a human-readable Markdown coverage report."""
    lines = ["# Autonomous Loop Coverage Audit", ""]
    lines.append(f"Status: {'PASS' if report.ok else 'FAIL'}")
    lines.append(f"Actions covered: {len(report.actions)}")
    lines.append(f"Scenarios cataloged: {len(report.scenarios)}")
    lines.append("")
    lines.append("## Errors")
    lines.extend(f"- {error}" for error in report.errors) if report.errors else lines.append("- none")
    lines.append("")
    lines.append("## Warnings")
    lines.extend(f"- {warning}" for warning in report.warnings) if report.warnings else lines.append("- none")
    lines.append("")
    lines.append("## Actions")
    lines.extend(f"- `{action}`" for action in report.actions)
    lines.append("")
    lines.append("## Scenarios")
    lines.extend(f"- `{scenario}`" for scenario in report.scenarios) if report.scenarios else lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> int:
    """CLI entrypoint for CI and operator use."""
    parser = argparse.ArgumentParser(description="Audit autonomous-loop static coverage.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of Markdown.")
    args = parser.parse_args()
    report = audit_coverage()
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print(format_markdown(report))
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
