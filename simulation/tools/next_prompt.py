"""Generate the exact autonomous-loop prompt for the next iteration.

Reads live GitHub state (open PRs, open issues, repo contents) plus local
disk state (persona files, scenarios) and outputs a self-contained
Markdown prompt that any agent (Claude / Grok / GPT) can execute as one
iteration of the autonomous loop.

The same priority list embedded in the scheduled routine
(``ai-erp-autonomous-loop``) is replicated here so a human or another tool
can produce the *exact* prompt that would fire next, on demand.

Usage
-----

::

    python -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation
    python -m simulation.tools.next_prompt --output /tmp/next.md
    python -m simulation.tools.next_prompt --probe-only      # just report what next is

Exit codes
----------

- ``0`` — prompt generated successfully.
- ``2`` — ``gh`` CLI unavailable or unauthenticated (we don't try to recover).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


_PERSONA_CATALOG = [
    "ari-orchestrator",
    "theo-architect",
    "mara-product-owner",
    "vera-risk-officer",
    "tessa-test-lead",
    "iris-security",
    "omar-audit",
    "rhea-release-manager",
    "cora-cost-architect",
    "prism-promptops",
    "echo-retrospective",
    "nico-program-manager",
    "lina-implementer",
]
_SCENARIO_CATALOG = [
    "001-suspend-cookie",
    "002-docs-only",
    "003-critical-migration",
    "004-hallucination-trap",
    "005-prior-approval-conflict",
]


@dataclass
class RepoState:
    """Snapshot of the GitHub state we care about for priority resolution."""

    open_prs: list[dict]
    open_issues: list[dict]
    existing_personas: set[str]
    existing_scenarios: set[str]
    prs_with_changes_requested: list[dict]


def _gh(args: list[str], repo: str) -> str:
    """Run a gh CLI subcommand; raise on non-zero. Returns stdout."""
    command = ["gh", *args]
    if args and args[0] != "api":
        command.extend(["-R", repo])

    result = subprocess.run(
        command,
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh failed: {result.stderr.strip()}")
    return result.stdout


def gather_repo_state(repo: str) -> RepoState:
    """Query gh CLI + repo contents for the inputs to priority resolution."""
    prs_json = _gh(
        ["pr", "list", "--state", "open", "--json",
         "number,title,reviewDecision,labels,author"],
        repo,
    )
    open_prs = json.loads(prs_json) if prs_json.strip() else []

    issues_json = _gh(
        ["issue", "list", "--state", "open", "--json",
         "number,title,labels,milestone"],
        repo,
    )
    open_issues = json.loads(issues_json) if issues_json.strip() else []

    try:
        personas_raw = _gh(["api", "repos/{owner}/{repo}/contents/.github/agent-prompts".replace("{owner}/{repo}", repo)], repo)
        personas_list = json.loads(personas_raw)
        existing = {
            entry["name"].removesuffix(".md")
            for entry in personas_list
            if entry["name"].endswith(".md") and not entry["name"].startswith("_")
        }
        existing.discard("README")
    except (RuntimeError, json.JSONDecodeError, KeyError):
        existing = set()

    try:
        scenarios_raw = _gh(["api", f"repos/{repo}/contents/simulation/scenarios"], repo)
        scenarios_list = json.loads(scenarios_raw)
        existing_scenarios = {
            entry["name"].removesuffix(".yml")
            for entry in scenarios_list
            if entry["name"].endswith(".yml") and not entry["name"].startswith("_")
        }
    except (RuntimeError, json.JSONDecodeError, KeyError):
        existing_scenarios = set()

    prs_with_changes_requested = [
        pr for pr in open_prs if pr.get("reviewDecision") == "CHANGES_REQUESTED"
    ]

    return RepoState(
        open_prs=open_prs,
        open_issues=open_issues,
        existing_personas=existing,
        existing_scenarios=existing_scenarios,
        prs_with_changes_requested=prs_with_changes_requested,
    )


def resolve_priority(state: RepoState) -> tuple[str, dict]:
    """Walk the priority list; return ``(priority_label, context_dict)``."""
    if len(state.open_prs) >= 5:
        return "skip", {"reason": f"{len(state.open_prs)} PRs already open — avoid pile-up"}

    if state.prs_with_changes_requested:
        oldest = min(state.prs_with_changes_requested, key=lambda p: p["number"])
        return "address_changes_requested", {"pr": oldest}

    next_persona = next(
        (p for p in _PERSONA_CATALOG if p not in state.existing_personas),
        None,
    )
    if next_persona:
        return "migrate_persona", {"persona_id": next_persona}

    next_scenario = next(
        (s for s in _SCENARIO_CATALOG if s not in state.existing_scenarios),
        None,
    )
    if next_scenario:
        return "implement_scenario", {"scenario_id": next_scenario}

    return "post_status_and_exit", {}


def render_prompt(repo: str, priority: str, context: dict) -> str:
    """Render the self-contained Markdown prompt for the resolved priority."""
    header = (
        f"# Autonomous loop — next iteration ({priority})\n\n"
        f"Generated by `simulation/tools/next_prompt.py` from live state of "
        f"`{repo}`. Self-contained. Paste into Claude / Grok / GPT-4o / etc.\n\n"
    )
    common_constraints = _common_constraints_block()

    body_renderers = {
        "address_changes_requested": _render_address_changes,
        "migrate_persona": _render_migrate_persona,
        "implement_scenario": _render_implement_scenario,
        "post_status_and_exit": _render_status_only,
        "skip": _render_skip,
    }
    body = body_renderers[priority](repo, context)
    return header + body + "\n\n" + common_constraints


def _common_constraints_block() -> str:
    return (
        "## Hard caps (NON-NEGOTIABLE)\n\n"
        "- Max 3 file Writes per iteration.\n"
        "- Max 2 sub-agent dispatches.\n"
        "- Max 6 Bash calls.\n"
        "- Per-iteration budget ceiling: $5.00.\n"
        "- Never bypass commit hooks (`--no-verify`, `SKIP_TESTS=1`).\n"
        "- Never run destructive git ops (`rm -rf`, `push --force`).\n"
        "- Sign every comment with the v0.3 YAML persona header (Persona / Role / "
        "Layer / Model / Source / Self-review conflict / Run-ID).\n"
        "- Every commit ends with `Co-Authored-By:` trailer naming your model.\n"
        "- Post end-of-run summary as a comment on Epic #1.\n"
    )


def _render_address_changes(repo: str, context: dict) -> str:
    pr = context["pr"]
    return (
        f"## Task\n\nAddress the oldest open PR with `CHANGES_REQUESTED`: "
        f"**#{pr['number']} — {pr['title']}**.\n\n"
        f"https://github.com/{repo}/pull/{pr['number']}\n\n"
        f"### Steps\n"
        f"1. Read the most recent `REQUEST_CHANGES` review comment.\n"
        f"2. Identify ONE concrete blocker to address (do not try to fix all at once).\n"
        f"3. `gh pr checkout {pr['number']} -R {repo}` and apply the fix.\n"
        f"4. Commit with a clear message naming the blocker.\n"
        f"5. Push.\n"
        f"6. Post a conversational reply to the reviewer's comment "
        f"acknowledging the fix.\n"
    )


def _render_migrate_persona(repo: str, context: dict) -> str:
    persona_id = context["persona_id"]
    return (
        f"## Task\n\nMigrate persona `{persona_id}` into "
        f"`.github/agent-prompts/{persona_id}.md`.\n\n"
        f"### Steps\n"
        f"1. Clone the repo (if not already).\n"
        f"2. Read `.github/agent-prompts/theo-architect.md` and "
        f"`ari-orchestrator.md` for the frontmatter contract pattern.\n"
        f"3. Create branch `feat/persona-{persona_id}`.\n"
        f"4. Write `.github/agent-prompts/{persona_id}.md` with the same "
        f"YAML frontmatter shape (`id`, `name`, `role`, `layer`, `version`, "
        f"`model_default`, `lens`, `verdict_enum`, `activates_on`, "
        f"`forbidden_paths`, `context_pack`, `inherits_preamble`, "
        f"`last_validated_against_model`, `last_sim_pass`, `frozen_sha`, "
        f"`owner: ci4me`).\n"
        f"5. Body: persona-specific mission, lens, authority, forbidden actions, "
        f"output format. Reference Discussion #2 for the original deliberation "
        f"that defined this persona's behavior.\n"
        f"6. Commit, push, open PR labeled "
        f"`risk:medium,area:agent-governance,agent:promptops,ready-for-review`.\n"
    )


def _render_implement_scenario(repo: str, context: dict) -> str:
    scenario_id = context["scenario_id"]
    return (
        f"## Task\n\nImplement simulation scenario `{scenario_id}.yml`.\n\n"
        f"### Steps\n"
        f"1. Read `simulation/scenarios/001-suspend-cookie.yml` for the schema shape.\n"
        f"2. Read `simulation/scenarios/_schema.yml` for the formal contract.\n"
        f"3. Create branch `feat/scenario-{scenario_id}`.\n"
        f"4. Write `simulation/scenarios/{scenario_id}.yml` per the schema "
        f"(`id`, `title`, `status: active`, `mock_pr` with `title`/`body`/`diff`, "
        f"`planted_flaws` with `id`/`name`/`severity`, `personas` with `id`/"
        f"`expected_verdict`/`must_catch`, `expected_overall_verdict`, "
        f"`pass_threshold` with `flaws_caught_pct`/`hallucinations_allowed`/"
        f"`per_persona_verdict_match`).\n"
        f"5. Validate locally: `python simulation/run.py --mode dry-run`.\n"
        f"6. Commit, push, open PR labeled "
        f"`risk:medium,area:agent-governance,area:ci,ready-for-review`.\n"
    )


def _render_status_only(repo: str, _: dict) -> str:
    return (
        f"## Task\n\n**Nothing to do.** All catalog items already addressed:\n\n"
        f"- All known personas exist in `.github/agent-prompts/`.\n"
        f"- All known scenarios exist in `simulation/scenarios/`.\n"
        f"- No PRs have `CHANGES_REQUESTED`.\n\n"
        f"### Action\n"
        f"Post a comment on Epic #1 reporting framework state + the fact that "
        f"the loop ran with no available work this iteration. Mention what would "
        f"make new work available (more personas in the catalog? new scenario "
        f"ideas? open issues without assigned work?).\n"
    )


def _render_skip(repo: str, context: dict) -> str:
    return (
        f"## Task\n\n**Skip this iteration.** Reason: {context['reason']}.\n\n"
        f"Open PRs awaiting review are accumulating. Avoid pile-up — let the "
        f"existing PRs land before queueing more.\n\n"
        f"### Action\n"
        f"Post a one-line comment on Epic #1 noting the skip + the open-PR count. "
        f"Exit 0.\n"
    )


def main() -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="ci4me/ai-erp-foundation")
    parser.add_argument("--output", type=Path, default=None,
                        help="Write prompt to this file instead of stdout.")
    parser.add_argument("--probe-only", action="store_true",
                        help="Print the resolved priority + context, skip the prompt body.")
    args = parser.parse_args()

    if not shutil.which("gh"):
        print("ERROR: gh CLI not found in PATH.", file=sys.stderr)
        return 2

    try:
        state = gather_repo_state(args.repo)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    priority, context = resolve_priority(state)
    if args.probe_only:
        print(f"priority: {priority}")
        print(f"context: {json.dumps(context, indent=2, default=str)}")
        print(f"open_prs: {len(state.open_prs)}")
        print(f"changes_requested: {len(state.prs_with_changes_requested)}")
        print(f"existing_personas: {sorted(state.existing_personas)}")
        print(f"existing_scenarios: {sorted(state.existing_scenarios)}")
        return 0

    prompt = render_prompt(args.repo, priority, context)
    if args.output:
        args.output.write_text(prompt)
        print(f"wrote {len(prompt)} chars to {args.output}", file=sys.stderr)
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
