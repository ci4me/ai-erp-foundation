"""Audit every persona prompt against the v0.3 operating-model contract.

Produces one acceptance matrix per persona, mirroring the
``nova-idea-generator`` example the operator shared. The audit is
mechanical — each criterion is a small predicate over the persona's
frontmatter, body, and any associated workflow file. The output is a
single Markdown report that the loop can post as a Discussion comment
and that the operator can paste into a follow-up issue.

Usage::

    python3 -m simulation.tools.persona_audit \\
        --output persona_audit_report.md

Criteria are tuned so the most common operating-model gaps surface as
``MISS`` (no `frozen_sha`, `last_sim_pass` without a run-id, no
regression scenario, etc.); everything else passes when the YAML
frontmatter contains the field.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_PROMPTS_DIR = REPO_ROOT / ".github" / "agent-prompts"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
SCENARIOS_DIR = REPO_ROOT / "simulation" / "scenarios"
SKIP_FILES = frozenset({"_preamble.md", "README.md", "roster.yml"})

REQUIRED_FRONTMATTER_FIELDS = (
    "id",
    "name",
    "owner",
    "layer",
    "persona",
    "model",
    "source",
    "frozen_sha",
    "last_sim_pass",
    "inherits_preamble",
    "verdict_enum",
)

CREATIVE_PERSONAS = frozenset({"nova-idea-generator", "echo-retrospective"})
REVIEW_VERDICTS = frozenset(
    {"APPROVE", "APPROVE_WITH_CONDITIONS", "REQUEST_CHANGES", "BLOCKED", "BLOCK", "REJECT"}
)


@dataclass
class CriterionResult:
    name: str
    status: str  # "PASS" / "MISS" / "PARTIAL" / "N/A"
    evidence: str


@dataclass
class PersonaAudit:
    id: str
    path: Path
    matrix: list[CriterionResult]

    @property
    def miss_count(self) -> int:
        return sum(1 for c in self.matrix if c.status == "MISS")

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.matrix if c.status == "PASS")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    if yaml is None:
        return {}, parts[2]
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), parts[2]


def _workflow_for_persona(persona_id: str) -> Path | None:
    """Find a workflow file whose name contains the persona id."""
    if not WORKFLOWS_DIR.exists():
        return None
    needle = persona_id.split("-", 1)[0]
    for path in WORKFLOWS_DIR.glob("*.yml"):
        if needle in path.name:
            return path
    return None


def _scenario_for_persona(persona_id: str) -> Path | None:
    if not SCENARIOS_DIR.exists():
        return None
    for path in SCENARIOS_DIR.glob("*.yml"):
        if persona_id.split("-", 1)[0] in path.name:
            return path
    return None


def audit_one(path: Path) -> PersonaAudit:
    text = path.read_text()
    fm, body = _split_frontmatter(text)
    persona_id = path.stem
    matrix: list[CriterionResult] = []

    # 1. Frontmatter v0.3 contract.
    missing_fm = [f for f in REQUIRED_FRONTMATTER_FIELDS if f not in fm]
    matrix.append(
        CriterionResult(
            name="Persona frontmatter satisfies v0.3 contract",
            status="PASS" if not missing_fm else "MISS",
            evidence=(
                f"`{path.as_posix()}` frontmatter contains all v0.3 fields"
                if not missing_fm
                else f"missing fields: {', '.join(missing_fm)}"
            ),
        )
    )

    # 2. verdict_enum appropriate.
    verdict = fm.get("verdict_enum") or []
    if isinstance(verdict, str):
        verdict = [v.strip() for v in verdict.replace(",", " ").split()]
    verdict_set = {v.upper() for v in verdict}
    if persona_id in CREATIVE_PERSONAS:
        status = "PASS" if verdict_set and not (verdict_set & REVIEW_VERDICTS) else "PARTIAL"
        evidence = f"creative persona; verdict_enum = {sorted(verdict_set) or 'MISSING'}"
    else:
        status = "PASS" if verdict_set & REVIEW_VERDICTS else "MISS"
        evidence = f"reviewer persona; verdict_enum = {sorted(verdict_set) or 'MISSING'}"
    matrix.append(CriterionResult(
        name="`verdict_enum` appropriate for the persona's role",
        status=status,
        evidence=evidence,
    ))

    # 3. inherits_preamble justified when false.
    inh = fm.get("inherits_preamble")
    if inh is False:
        status = "PASS" if "preamble" in body.lower() or "divergent" in body.lower() else "PARTIAL"
        evidence = "inherits_preamble=false; rationale present in body" if status == "PASS" else "false but no justification found"
    else:
        status = "N/A"
        evidence = "inherits_preamble=true"
    matrix.append(CriterionResult(
        name="`inherits_preamble false` justified for divergent role",
        status=status,
        evidence=evidence,
    ))

    # 4. Hard caps defined.
    has_caps = bool(re.search(r"(?i)hard\s+(rules|caps)", body))
    matrix.append(CriterionResult(
        name="Hard caps / hard rules section defined",
        status="PASS" if has_caps else "MISS",
        evidence=f"`{path.as_posix()}` mentions hard rules/caps" if has_caps else "no hard rules section",
    ))

    # 5. Anti-duplication / idempotency.
    has_idem = bool(re.search(r"(?i)(anti-?dup|idempoten|do not (re)?post|never repeat)", body))
    matrix.append(CriterionResult(
        name="Anti-duplication / idempotency rule",
        status="PASS" if has_idem else "MISS",
        evidence="explicit anti-duplication rule" if has_idem else "no anti-duplication clause",
    ))

    # 6. Cost ceiling.
    has_budget = bool(re.search(r"(?i)budget|session_budget|cost ceiling|\$\d", body))
    matrix.append(CriterionResult(
        name="Cost / resource ceiling stated",
        status="PASS" if has_budget else "MISS",
        evidence="budget/cost ceiling mentioned" if has_budget else "no explicit budget ceiling",
    ))

    # 7. SHA-pinned actions in associated workflow.
    workflow = _workflow_for_persona(persona_id)
    if workflow:
        wf_text = workflow.read_text()
        sha_pinned = bool(re.search(r"uses:\s*\S+@[0-9a-f]{40}", wf_text))
        matrix.append(CriterionResult(
            name="SHA-pinned workflow actions",
            status="PASS" if sha_pinned else "MISS",
            evidence=f"`{workflow.as_posix()}` pins actions to SHAs" if sha_pinned else f"`{workflow.as_posix()}` uses tag refs",
        ))
    else:
        matrix.append(CriterionResult(
            name="SHA-pinned workflow actions",
            status="N/A",
            evidence="no dedicated workflow for this persona",
        ))

    # 8. Genesis-circularity guard.
    has_genesis = bool(re.search(r"(?i)genesis|circular(ity)?|self-?modif", body))
    matrix.append(CriterionResult(
        name="Genesis-circularity guard",
        status="PASS" if has_genesis else "MISS",
        evidence="explicit genesis-circularity reminder" if has_genesis else "no genesis-circularity clause",
    ))

    # 9. Forbidden paths cover operating-model surface.
    has_forbidden = bool(re.search(r"(?i)forbidden|do not modify|never edit", body)) and (
        ".github/agent-prompts" in body or "operating-model" in body or "amendment" in body
    )
    matrix.append(CriterionResult(
        name="Forbidden paths cover operating-model surface",
        status="PASS" if has_forbidden else "MISS",
        evidence="forbidden block mentions operating-model paths" if has_forbidden else "no forbidden block for operating-model paths",
    ))

    # 10. Regression scenario exists.
    scenario = _scenario_for_persona(persona_id)
    matrix.append(CriterionResult(
        name="Regression scenario exists in simulation/scenarios/",
        status="PASS" if scenario else "MISS",
        evidence=f"`{scenario.as_posix()}`" if scenario else "no scenario file matching this persona",
    ))

    # 11. frozen_sha populated.
    sha = str(fm.get("frozen_sha") or "").strip()
    matrix.append(CriterionResult(
        name="`frozen_sha` populated before live activation",
        status="PASS" if sha and sha not in {"", "TBD", "PENDING"} else "MISS",
        evidence=f"frozen_sha={sha}" if sha else "frozen_sha is empty",
    ))

    # 12. last_sim_pass references a run-id.
    last_pass = str(fm.get("last_sim_pass") or "")
    has_runid = bool(re.search(r"run[-_]id|2026-|2025-", last_pass)) and len(last_pass.split()) > 1
    matrix.append(CriterionResult(
        name="`last_sim_pass` linked to a run-id",
        status="PASS" if has_runid else "MISS",
        evidence=f"last_sim_pass = {last_pass!r}" if last_pass else "last_sim_pass missing",
    ))

    return PersonaAudit(id=persona_id, path=path, matrix=matrix)


def audit_all() -> list[PersonaAudit]:
    out: list[PersonaAudit] = []
    for path in sorted(AGENT_PROMPTS_DIR.glob("*.md")):
        if path.name in SKIP_FILES:
            continue
        out.append(audit_one(path))
    return out


def _status_emoji(status: str) -> str:
    return {
        "PASS": "✅ PASS",
        "MISS": "❌ MISS",
        "PARTIAL": "⚠️ PARTIAL",
        "N/A": "🔄 N/A",
    }.get(status, status)


def render_matrix(audit: PersonaAudit) -> str:
    lines = [f"## 🧑‍💻 Persona: `{audit.id}`", "",
             "| Criterion | Status | Evidence |",
             "|-----------|--------|----------|"]
    for c in audit.matrix:
        ev = c.evidence.replace("|", "\\|")
        lines.append(f"| {c.name} | {_status_emoji(c.status)} | {ev} |")
    lines.append("")
    lines.append(f"**Counts:** {audit.pass_count} PASS · {audit.miss_count} MISS · {len(audit.matrix)} total")
    if audit.miss_count:
        lines.append("")
        lines.append("<details><summary>Missing items to fix</summary>")
        lines.append("")
        for c in audit.matrix:
            if c.status == "MISS":
                lines.append(f"- [ ] {c.name} — {c.evidence}")
        lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def render_report(audits: list[PersonaAudit]) -> str:
    total_pass = sum(a.pass_count for a in audits)
    total_miss = sum(a.miss_count for a in audits)
    total_crit = sum(len(a.matrix) for a in audits)
    summary = [
        "# 🧪 Persona Acceptance Matrices — Full Audit",
        "",
        f"- **Personas audited**: {len(audits)}",
        f"- **Total PASS**: {total_pass} / {total_crit} ({100 * total_pass / max(total_crit, 1):.0f}%)",
        f"- **Total MISS**: {total_miss}",
        "",
        "## Summary table",
        "",
        "| Persona | PASS | MISS | Total |",
        "|---------|------|------|-------|",
    ]
    for audit in audits:
        summary.append(
            f"| `{audit.id}` | {audit.pass_count} | {audit.miss_count} | {len(audit.matrix)} |"
        )
    summary.append("")
    summary.append("---")
    summary.append("")
    blocks = "\n".join(render_matrix(a) for a in audits)
    return "\n".join(summary) + blocks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="persona_audit_report.md")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    audits = audit_all()
    report = render_report(audits)
    Path(args.output).write_text(report)
    miss_total = sum(a.miss_count for a in audits)
    print(f"audited {len(audits)} personas, {miss_total} missing criteria → {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))


__all__ = [
    "PersonaAudit",
    "audit_all",
    "audit_one",
    "main",
    "render_matrix",
    "render_report",
]
