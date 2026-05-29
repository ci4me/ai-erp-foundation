#!/usr/bin/env python3
"""Comprehensive audit of markers, actions, templates, and GitHub-feature wiring.

Adapted to this repo's real schema:

- ``markers.yml`` is a mapping with three sections — ``markers`` (one entry per
  catalog action), ``request_markers``, and ``collaboration_markers``. It is NOT
  a flat ``- name:`` list.
- ``catalog.yml`` actions use ``id`` + ``template`` (not ``action`` + ...).

Exit code 0 when everything required is present; 1 otherwise. Warnings (⚠️) for
optional GitHub-feature files do not fail the audit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
# Allow running as a file (``python3 simulation/tools/full_audit.py``), not only
# as a module, by ensuring the repo root is importable.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulation.tools import marker_registry  # noqa: E402
TEMPLATES = ROOT / ".github" / "action-templates"

REQUIRED_COLLABORATION_MARKERS = [
    "REQUEST-INFO", "RESPONSE", "ARGUMENT", "COUNTER-PROPOSAL", "REBUTTAL",
    "EVIDENCE", "RESOLUTION", "OBJECTION", "ESCALATION", "EXPLANATION",
    "DECISION-FROM-LEAD", "CONSENSUS-REACHED",
    "DECOMPOSE-REQUEST", "SUB-TASK", "DECOMPOSITION-PLAN",
    "TEST-REPORT", "PHASE-CHANGE",
]
REQUIRED_REQUEST_MARKERS = [
    "REQUEST-REPLY-FROM", "REQUEST-REVIEW-FROM", "REQUEST-APPROVAL-FROM", "QUESTION-TO",
]
REQUIRED_PHASE_LABELS = ["planning", "implementation", "testing", "acceptance", "done"]
COLLABORATION_TEMPLATES = [
    "request_info.md", "debate.md", "resolve_debate.md", "escalate.md",
    "record_adr.md", "explain.md", "reach_consensus.md",
    "decompose_feature.md", "create_sub_issues.md",
    "run_tests.md", "phase_gate.md", "acceptance_review.md",
    "rework_from_rejection.md", "triage_test_failures.md",
]
# Problem types that must be wired into the planner's analyzer.
REQUIRED_DETECTORS = [
    "UNANSWERED_REQUEST", "REVIEW_DEADLOCK", "UNANSWERED_REQUEST_INFO",
    "UNRESOLVED_DEBATE", "MISSING_EXPLANATION", "UNRECORDED_ADR",
    "EPIC_UNDECOMPOSED", "SUBTASKS_NOT_CREATED", "BLOCKED_BY_DEPENDENCY",
    "PHASE_GATE_READY", "TESTING_REQUIRED", "TESTING_FAILED",
    "ACCEPTANCE_REQUIRED", "ACCEPTANCE_BLOCKED",
]


def _present(prefixes: tuple[str, ...]) -> set[str]:
    return {p.rstrip(":") for p in prefixes}


def audit_markers() -> bool:
    """Action↔marker coverage is 1:1, and request/collaboration markers exist."""
    ok = True

    catalog = yaml.safe_load((TEMPLATES / "catalog.yml").read_text()) or {}
    action_ids = {a["id"] for a in catalog.get("actions", [])}
    coverage_errors = marker_registry.validate_catalog_coverage(action_ids)
    if coverage_errors:
        print("❌ Action↔marker coverage broken:")
        for err in coverage_errors:
            print(f"   - {err}")
        ok = False
    else:
        print(f"✅ Action↔marker coverage intact ({len(action_ids)} actions).")

    collab = _present(marker_registry.collaboration_marker_names())
    missing_collab = set(REQUIRED_COLLABORATION_MARKERS) - collab
    if missing_collab:
        print(f"❌ Missing collaboration markers: {sorted(missing_collab)}")
        ok = False
    else:
        print(f"✅ All {len(REQUIRED_COLLABORATION_MARKERS)} collaboration markers present.")

    request = _present(marker_registry.request_marker_names())
    missing_request = set(REQUIRED_REQUEST_MARKERS) - request
    if missing_request:
        print(f"❌ Missing request markers: {sorted(missing_request)}")
        ok = False
    else:
        print(f"✅ All {len(REQUIRED_REQUEST_MARKERS)} request markers present.")

    raw = yaml.safe_load((TEMPLATES / "markers.yml").read_text()) or {}
    phase_labels = raw.get("phase_labels") or {}
    missing_phases = [p for p in REQUIRED_PHASE_LABELS if p not in phase_labels]
    if missing_phases:
        print(f"❌ Missing phase labels: {missing_phases}")
        ok = False
    else:
        print(f"✅ All {len(REQUIRED_PHASE_LABELS)} phase labels defined.")

    return ok


def audit_actions() -> bool:
    """Every catalog action's template file exists."""
    catalog = yaml.safe_load((TEMPLATES / "catalog.yml").read_text()) or {}
    missing = [
        a["id"] for a in catalog.get("actions", [])
        if not (TEMPLATES / a["template"]).exists()
    ]
    if missing:
        print(f"❌ Catalog actions missing templates: {missing}")
        return False
    print("✅ All catalog action templates exist.")
    return True


def audit_collaboration_templates() -> bool:
    """The collaboration action templates exist."""
    missing = [name for name in COLLABORATION_TEMPLATES if not (TEMPLATES / name).exists()]
    if missing:
        print(f"❌ Missing collaboration templates: {missing}")
        return False
    print(f"✅ All {len(COLLABORATION_TEMPLATES)} collaboration templates exist.")
    return True


def audit_production_readiness() -> bool:
    """Verify the config knob and analyzer detectors added for hardening."""
    ok = True

    from simulation.tools import config, state_analyzer

    if not isinstance(getattr(config, "DEBATE_RESOLUTION_TIMEOUT_HOURS", None), int):
        print("❌ config.DEBATE_RESOLUTION_TIMEOUT_HOURS is missing or not an int.")
        ok = False
    else:
        print(f"✅ config.DEBATE_RESOLUTION_TIMEOUT_HOURS = "
              f"{config.DEBATE_RESOLUTION_TIMEOUT_HOURS}.")

    if getattr(config, "EPIC_DETECTION_MODE", None) not in ("label", "marker", "heuristic"):
        print("❌ config.EPIC_DETECTION_MODE is missing or invalid.")
        ok = False
    else:
        print(f"✅ config.EPIC_DETECTION_MODE = {config.EPIC_DETECTION_MODE}.")

    analyzer_src = (ROOT / "simulation" / "tools" / "state_analyzer.py").read_text()
    missing = [d for d in REQUIRED_DETECTORS if d not in analyzer_src]
    if missing:
        print(f"❌ analyzer missing problem detectors: {missing}")
        ok = False
    else:
        print(f"✅ All {len(REQUIRED_DETECTORS)} planner detectors present in state_analyzer.")

    # The plan builder must have a fixer registered for the corrective detectors.
    from simulation.tools import plan_builder

    for needed in (
        "MISSING_EXPLANATION", "UNRECORDED_ADR", "UNRESOLVED_DEBATE",
        "EPIC_UNDECOMPOSED", "SUBTASKS_NOT_CREATED",
        "PHASE_GATE_READY", "TESTING_REQUIRED", "TESTING_FAILED",
        "ACCEPTANCE_REQUIRED", "ACCEPTANCE_BLOCKED",
    ):
        if needed not in plan_builder._FIXERS:
            print(f"❌ plan_builder has no fixer for {needed}.")
            ok = False
    return ok


def audit_github_features() -> bool:
    """Warn (don't fail) on optional GitHub-feature wiring."""
    if not (ROOT / ".github" / "CODEOWNERS").exists():
        print("⚠️  .github/CODEOWNERS missing (run scripts/generate_codeowners.py).")
    if not (ROOT / "scripts" / "enforce_branch_protection.py").exists():
        print("⚠️  scripts/enforce_branch_protection.py missing.")
    if not list((ROOT / ".github" / "workflows").glob("*feedback*")):
        print("⚠️  No CI feedback workflow found (.github/workflows/ci-feedback.yml).")
    return True  # advisory only


def main() -> int:
    print("=== Full Audit ===")
    ok = True
    ok &= audit_markers()
    ok &= audit_actions()
    ok &= audit_collaboration_templates()
    ok &= audit_production_readiness()
    audit_github_features()
    if ok:
        print("\n🎉 Audit passed.")
        return 0
    print("\n⚠️  Audit found issues. Fix them or open TEAM-REQUEST issues.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
