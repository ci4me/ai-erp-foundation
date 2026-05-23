"""next_prompt.py — v2 — Deterministic action chooser + dumb-model prompt renderer.

Inspects live repository state via `gh` CLI and emits a SELF-CONTAINED, numbered,
copy-pasteable prompt for the next AI persona to execute. Prompts are designed
for "dumb" models (Haiku, Llama-3, GPT-3.5-class): every step is numbered, every
command is exact, every expected output is spelled out, every failure path is
explicit. No model-specific syntax.

Priority cascade (NEVER returns None):
    1.  execute_merge          — Sim-Human approval present and gate green
    2.  sim_human_approval     — gate green, awaiting final human-proxy sign-off
    3.  merge_gate             — Rhea must run the merge-gate checklist
    4.  review_pr              — open PR needs persona reviews
    5.  address_changes        — CHANGES_REQUESTED outstanding on a PR
    6.  migrate_persona        — persona prompt file missing or stale
    7.  implement_scenario     — scenario lacks scorecard
    8.  retrospective          — >7 days since last retro
    9.  brainstorm             — >30 days since last brainstorm
    10. meta_critique          — >30 days since last meta-critique
    11. ari_triage             — fallback; orchestrator decides

Usage:
    python next_prompt.py --probe
    python next_prompt.py --emit
    python next_prompt.py --emit-json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # YAML is optional for --probe; required for scenarios.

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO = "ci4me/ai-erp-foundation"
EPIC_ISSUE = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / ".github" / "agent-prompts"
SCENARIOS_DIR = REPO_ROOT / "simulation" / "scenarios"
SCORECARDS_DIR = REPO_ROOT / "simulation" / "scorecards"

PERSONAS: list[str] = [
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
    "nova-idea-generator",
]

SCENARIOS: list[str] = [
    "001-suspend-cookie",
    "002-docs-only",
    "003-critical-migration",
    "004-hallucination-trap",
    "005-prior-approval-conflict",
]

CADENCE_RETRO_DAYS = 7
CADENCE_BRAINSTORM_DAYS = 30
CADENCE_METACRITIQUE_DAYS = 30

# Comment markers we scan in PR threads / Epic comments.
MARKER_RHEA_VERDICT = "RHEA-VERDICT:"
MARKER_SIM_HUMAN_APPROVAL = "SIM-HUMAN-APPROVAL:"
MARKER_PERSONA_REVIEW = "PERSONA-REVIEW:"
MARKER_RETRO = "RETRO-LOG:"
MARKER_BRAINSTORM = "BRAINSTORM-LOG:"
MARKER_METACRITIQUE = "META-CRITIQUE-LOG:"


def run_gh(args: list[str], *, check: bool = False) -> tuple[int, str, str]:
    """Execute a `gh` subcommand. Returns (returncode, stdout, stderr)."""
    if shutil.which("gh") is None:
        return 127, "", "gh CLI not found on PATH"
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=60,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "gh call timed out"
    except subprocess.CalledProcessError as exc:
        return exc.returncode, exc.stdout or "", exc.stderr or ""


def gh_json(args: list[str]) -> Any:
    """Run `gh` and parse stdout as JSON. Returns {} on failure."""
    code, out, _ = run_gh(args)
    if code != 0 or not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


@dataclass
class PRSnapshot:
    number: int
    title: str
    labels: list[str]
    mergeable: str
    review_decision: str
    ci_state: str
    comments: list[dict[str, Any]] = field(default_factory=list)
    has_rhea_approve: bool = False
    has_sim_human_approve: bool = False
    has_changes_requested: bool = False
    persona_reviews_done: set[str] = field(default_factory=set)


@dataclass
class RepoState:
    open_prs: list[PRSnapshot] = field(default_factory=list)
    missing_personas: list[str] = field(default_factory=list)
    stale_personas: list[str] = field(default_factory=list)
    scenarios_without_scorecards: list[str] = field(default_factory=list)
    days_since_retro: int | None = None
    days_since_brainstorm: int | None = None
    days_since_metacritique: int | None = None
    notes: list[str] = field(default_factory=list)


def inspect_open_prs() -> list[PRSnapshot]:
    raw = gh_json([
        "pr", "list", "-R", REPO, "--state", "open",
        "--json", "number,title,labels",
        "--limit", "50",
    ])
    if not isinstance(raw, list):
        return []
    snapshots: list[PRSnapshot] = []
    for entry in raw:
        number = entry.get("number")
        if not isinstance(number, int):
            continue
        labels = [lbl.get("name", "") for lbl in entry.get("labels", []) if isinstance(lbl, dict)]
        detail = gh_json([
            "pr", "view", str(number), "-R", REPO,
            "--json", "mergeable,reviewDecision,statusCheckRollup,comments",
        ])
        mergeable = detail.get("mergeable", "UNKNOWN") if isinstance(detail, dict) else "UNKNOWN"
        review_decision = detail.get("reviewDecision", "") if isinstance(detail, dict) else ""
        ci_state = _summarize_ci(detail.get("statusCheckRollup", []) if isinstance(detail, dict) else [])
        comments = detail.get("comments", []) if isinstance(detail, dict) else []
        snap = PRSnapshot(
            number=number,
            title=entry.get("title", ""),
            labels=labels,
            mergeable=mergeable or "UNKNOWN",
            review_decision=review_decision or "",
            ci_state=ci_state,
            comments=comments if isinstance(comments, list) else [],
        )
        _scan_pr_comments(snap)
        snapshots.append(snap)
    return snapshots

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

def _summarize_ci(rollup: list[Any]) -> str:
    if not rollup:
        return "UNKNOWN"
    states: set[str] = set()
    for check in rollup:
        if not isinstance(check, dict):
            continue
        state = check.get("state") or check.get("conclusion") or ""
        if state:
            states.add(state.upper())
    if {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT"} & states:
        return "FAILURE"
    if {"PENDING", "QUEUED", "IN_PROGRESS"} & states:
        return "PENDING"
    if states <= {"SUCCESS", "NEUTRAL", "SKIPPED"} and states:
        return "SUCCESS"
    return "UNKNOWN"


def _scan_pr_comments(snap: PRSnapshot) -> None:
    for comment in snap.comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body", "") or ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith(MARKER_RHEA_VERDICT):
                if "APPROVE" in stripped.upper():
                    snap.has_rhea_approve = True
            elif stripped.startswith(MARKER_SIM_HUMAN_APPROVAL):
                if "MERGE" in stripped.upper() or "APPROVE" in stripped.upper():
                    snap.has_sim_human_approve = True
            elif stripped.startswith(MARKER_PERSONA_REVIEW):
                tail = stripped[len(MARKER_PERSONA_REVIEW):].strip()
                parts = tail.split()
                if parts:
                    snap.persona_reviews_done.add(parts[0].lower())
    if snap.review_decision == "CHANGES_REQUESTED":
        snap.has_changes_requested = True


def inspect_personas() -> tuple[list[str], list[str]]:
    missing: list[str] = []
    stale: list[str] = []
    if not PROMPTS_DIR.exists():
        return PERSONAS[:], []
    threshold = datetime.now(tz=timezone.utc) - timedelta(days=60)
    for persona in PERSONAS:
        path = PROMPTS_DIR / f"{persona}.md"
        if not path.exists():
            missing.append(persona)
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < threshold:
            stale.append(persona)
    return missing, stale


def inspect_scenarios() -> list[str]:
    without: list[str] = []
    for sid in SCENARIOS:
        scorecard = SCORECARDS_DIR / f"{sid}.json"
        scenario_file = SCENARIOS_DIR / f"{sid}.yml"
        if scenario_file.exists() and not scorecard.exists():
            without.append(sid)
    return without


def inspect_cadence() -> tuple[int | None, int | None, int | None]:
    detail = gh_json([
        "issue", "view", str(EPIC_ISSUE), "-R", REPO,
        "--json", "comments",
    ])
    comments = detail.get("comments", []) if isinstance(detail, dict) else []
    if not isinstance(comments, list):
        return None, None, None
    last_retro: datetime | None = None
    last_brain: datetime | None = None
    last_meta: datetime | None = None
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body", "") or ""
        created = _parse_ts(comment.get("createdAt", ""))
        if created is None:
            continue
        if MARKER_RETRO in body and (last_retro is None or created > last_retro):
            last_retro = created
        if MARKER_BRAINSTORM in body and (last_brain is None or created > last_brain):
            last_brain = created
        if MARKER_METACRITIQUE in body and (last_meta is None or created > last_meta):
            last_meta = created
    now = datetime.now(tz=timezone.utc)
    return (
        (now - last_retro).days if last_retro else None,
        (now - last_brain).days if last_brain else None,
        (now - last_meta).days if last_meta else None,
    )


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def gather_state() -> RepoState:
    state = RepoState()
    state.open_prs = inspect_open_prs()
    state.missing_personas, state.stale_personas = inspect_personas()
    state.scenarios_without_scorecards = inspect_scenarios()
    retro, brain, meta = inspect_cadence()
    state.days_since_retro = retro
    state.days_since_brainstorm = brain
    state.days_since_metacritique = meta
    return state


def required_reviewers(labels: list[str]) -> list[str]:
    reviewers: set[str] = {"theo-architect", "rhea-release-manager"}
    lset = {lbl.lower() for lbl in labels}
    if "risk:high" in lset or "risk:critical" in lset:
        reviewers.update({"vera-risk-officer", "iris-security", "omar-audit"})
    if "area:agent-governance" in lset:
        reviewers.update({"prism-promptops", "mara-product-owner"})
    if "area:ci" in lset:
        reviewers.add("iris-security")
    if "area:cost" in lset or "agent:cost" in lset:
        reviewers.add("cora-cost-architect")
    if "area:docs" in lset:
        reviewers.add("mara-product-owner")
    return sorted(reviewers)


def choose_action(state: RepoState) -> dict[str, Any]:
    """Walk the 11-level cascade. NEVER returns None."""
    for pr in state.open_prs:
        if (pr.has_sim_human_approve and pr.has_rhea_approve
                and pr.mergeable == "MERGEABLE"
                and pr.review_decision in {"APPROVED", ""}
                and pr.ci_state == "SUCCESS"):
            return {"action": "execute_merge", "persona": "rhea-release-manager",
                    "pr": pr.number, "pr_title": pr.title, "labels": pr.labels}

    for pr in state.open_prs:
        if (pr.has_rhea_approve and not pr.has_sim_human_approve
                and pr.mergeable == "MERGEABLE"
                and pr.review_decision in {"APPROVED", ""}
                and pr.ci_state == "SUCCESS"):
            return {"action": "sim_human_approval", "persona": "sim-human-proxy",
                    "pr": pr.number, "pr_title": pr.title, "labels": pr.labels}

    for pr in state.open_prs:
        required = set(required_reviewers(pr.labels))
        if (required <= pr.persona_reviews_done
                and not pr.has_rhea_approve
                and pr.review_decision != "CHANGES_REQUESTED"):
            return {"action": "merge_gate", "persona": "rhea-release-manager",
                    "pr": pr.number, "pr_title": pr.title, "labels": pr.labels,
                    "required_reviewers": sorted(required)}

    for pr in state.open_prs:
        if pr.has_changes_requested:
            continue
        required = set(required_reviewers(pr.labels))
        outstanding = sorted(required - pr.persona_reviews_done)
        if outstanding:
            return {"action": "review_pr", "persona": outstanding[0],
                    "pr": pr.number, "pr_title": pr.title, "labels": pr.labels,
                    "outstanding_reviewers": outstanding}

    for pr in state.open_prs:
        if pr.has_changes_requested:
            return {"action": "address_changes", "persona": "lina-implementer",
                    "pr": pr.number, "pr_title": pr.title, "labels": pr.labels}

    if state.missing_personas or state.stale_personas:
        target = state.missing_personas[0] if state.missing_personas else state.stale_personas[0]
        return {"action": "migrate_persona", "persona": "prism-promptops",
                "target_persona": target,
                "missing": state.missing_personas, "stale": state.stale_personas}

    if state.scenarios_without_scorecards:
        return {"action": "implement_scenario", "persona": "lina-implementer",
                "scenario": state.scenarios_without_scorecards[0],
                "all_missing": state.scenarios_without_scorecards}

    if state.days_since_retro is None or state.days_since_retro >= CADENCE_RETRO_DAYS:
        return {"action": "retrospective", "persona": "echo-retrospective",
                "days_since": state.days_since_retro}

    if state.days_since_brainstorm is None or state.days_since_brainstorm >= CADENCE_BRAINSTORM_DAYS:
        return {"action": "brainstorm", "persona": "nova-idea-generator",
                "days_since": state.days_since_brainstorm}

    if state.days_since_metacritique is None or state.days_since_metacritique >= CADENCE_METACRITIQUE_DAYS:
        return {"action": "meta_critique", "persona": "prism-promptops",
                "days_since": state.days_since_metacritique}

    return {"action": "ari_triage", "persona": "ari-orchestrator",
            "reason": "No higher-priority action detected; orchestrator should reassess."}


def _common_header(persona: str, action: str) -> str:
    return (
        f"# Task for persona: {persona}\n"
        f"# Action type: {action}\n"
        f"# Repository: {REPO}\n"
        f"# Generated by: simulation/tools/next_prompt.py (v2)\n"
        f"# Follow EVERY step in order. Do not skip. Do not improvise.\n"
        f"# If a step says 'STOP', stop immediately and post the required comment.\n"
    )


def render_execute_merge(ctx: dict[str, Any]) -> str:
    pr = ctx["pr"]
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Rhea (Release Manager). PR #{pr} ({ctx.get('pr_title', '')}) has Sim-Human approval and a green gate. Execute the merge.

## Step-by-step

**Step 1.** Confirm the PR is still mergeable. Run this exact command:
```bash
gh pr view {pr} -R {REPO} --json mergeable,reviewDecision,statusCheckRollup
```
**Expected output contains:** `"mergeable":"MERGEABLE"` AND (`"reviewDecision":"APPROVED"` OR no `reviewDecision` field).
**If output contains `"mergeable":"CONFLICTING"`:** STOP. Post:
```bash
gh pr comment {pr} -R {REPO} --body "RHEA-VERDICT: BLOCKED — PR is CONFLICTING. Rebase required."
```
Exit.
**If output contains `"reviewDecision":"CHANGES_REQUESTED"`:** STOP. Post:
```bash
gh pr comment {pr} -R {REPO} --body "RHEA-VERDICT: BLOCKED — CHANGES_REQUESTED outstanding. Hand back to Lina."
```
Exit.

**Step 2.** Confirm CI is green:
```bash
gh pr checks {pr} -R {REPO}
```
**Expected:** every row ends with `pass`.
**If any row ends with `fail` or `pending`:** STOP. Post: `RHEA-VERDICT: BLOCKED — CI not green.` Exit.

**Step 3.** Perform the squash-merge (NEVER --admin):
```bash
gh pr merge {pr} -R {REPO} --squash --delete-branch
```

**Step 4 (self-verification).** Confirm the PR closed:
```bash
gh pr view {pr} -R {REPO} --json state,mergedAt
```
**Expected output contains:** `"state":"MERGED"` AND non-empty `mergedAt`.

**Step 5.** Post the merge log on Epic #{EPIC_ISSUE}:
```bash
gh issue comment {EPIC_ISSUE} -R {REPO} --body "RHEA-VERDICT: MERGED PR #{pr} at $(date -u +%FT%TZ)."
```

## Common mistakes to avoid
- Do NOT use `--merge` or `--rebase` or `--admin`. We always squash; never admin-bypass.
- Do NOT skip Step 4. A "succeeded" CLI call is not proof; only the API state field counts.
- Do NOT post the merge comment if Step 4 fails — false audit record.
"""


def render_sim_human_approval(ctx: dict[str, Any]) -> str:
    pr = ctx["pr"]
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are the Sim-Human Proxy (DEMO ONLY — maintainer stand-in). PR #{pr} ({ctx.get('pr_title', '')}) passed the Rhea gate. Decide MERGE or HOLD.

## Step-by-step

**Step 1.** Read the PR + Rhea's verdict:
```bash
gh pr view {pr} -R {REPO} --json title,body,labels,comments
```
**What to look for:** at least one comment whose body contains the EXACT substring `RHEA-VERDICT: APPROVE`.
**If no such comment:** STOP. This task was scheduled in error; exit.

**Step 2.** Inspect the diff:
```bash
gh pr diff {pr} -R {REPO}
```
**What to look for:** scope matches PR title; no unexpected files (`.env`, credentials, large binaries).
**If unexpected files appear:** go to Step 4a.

**Step 3.** Confirm gate still green:
```bash
gh pr view {pr} -R {REPO} --json mergeable,reviewDecision,statusCheckRollup
```
**Expected:** `"mergeable":"MERGEABLE"`. **If not:** go to Step 4a.

**Step 4 (HAPPY PATH — approve).** Post this EXACT comment (regex `^SIM-HUMAN-APPROVAL: MERGE` is parsed):
```bash
gh pr comment {pr} -R {REPO} --body "SIM-HUMAN-APPROVAL: MERGE — scope verified, gate green, no unexpected files."
```

**Step 4a (HOLD path).** Post instead:
```bash
gh pr comment {pr} -R {REPO} --body "SIM-HUMAN-APPROVAL: HOLD — <one-sentence reason, max 120 chars>"
```
Exit.

**Step 5 (self-verification).** Confirm:
```bash
gh pr view {pr} -R {REPO} --json comments --jq '.comments[-1].body'
```
**Expected:** starts with `SIM-HUMAN-APPROVAL:`.

## Common mistakes to avoid
- The marker is `SIM-HUMAN-APPROVAL:` exactly. `LGTM` or `approved` are ignored.
- Do NOT approve a PR whose diff contains files you did not expect from the title.
- One comment per PR. Do not post both MERGE and HOLD.
"""


def render_merge_gate(ctx: dict[str, Any]) -> str:
    pr = ctx["pr"]
    required = ctx.get("required_reviewers", [])
    required_block = "\n".join(f"   - `{r}`" for r in required) or "   (none)"
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Rhea (Release Manager). PR #{pr} ({ctx.get('pr_title', '')}) has every required persona review. Run the checklist.

## Required reviewers (from labels {ctx.get('labels', [])})
{required_block}

## Step-by-step

**Step 1.** List all `PERSONA-REVIEW:` markers:
```bash
gh pr view {pr} -R {REPO} --json comments --jq '.comments[].body' | grep -E '^PERSONA-REVIEW:'
```
**Expected:** every required persona above appears with verdict `APPROVE`.
**Regex for a valid line:** `^PERSONA-REVIEW: <persona-id> (APPROVE|REJECT)( — .*)?$`
**If any required is missing or `REJECT`:** STOP. Post:
```bash
gh pr comment {pr} -R {REPO} --body "RHEA-VERDICT: HOLD — missing/rejecting reviewers: <list>"
```
Exit.

**Step 2.** Confirm CI green:
```bash
gh pr checks {pr} -R {REPO}
```
**If not:** post `RHEA-VERDICT: HOLD — CI not green.` Exit.

**Step 3.** Confirm mergeable:
```bash
gh pr view {pr} -R {REPO} --json mergeable
```
**Expected:** `"mergeable":"MERGEABLE"`.
**If `CONFLICTING`:** post `RHEA-VERDICT: HOLD — rebase required.` Exit.
**If `UNKNOWN`:** wait 30s, re-run once. Still unknown → post `RHEA-VERDICT: HOLD — mergeable status unknown.` Exit.

**Step 4 (HAPPY PATH).** Post the verdict (this EXACT marker unlocks Sim-Human):
```bash
gh pr comment {pr} -R {REPO} --body "RHEA-VERDICT: APPROVE — all required reviewers green, CI pass, mergeable."
```

**Step 5 (self-verification).**
```bash
gh pr view {pr} -R {REPO} --json comments --jq '.comments[-1].body'
```
**Expected:** starts with `RHEA-VERDICT: APPROVE`.

## Common mistakes to avoid
- Marker MUST be `RHEA-VERDICT:` followed by `APPROVE | HOLD | BLOCKED | MERGED`.
- Do NOT merge from this prompt — `execute_merge` is the separate action.
- Do NOT approve if any required persona is missing.
"""


def render_review_pr(ctx: dict[str, Any]) -> str:
    pr = ctx["pr"]
    persona = ctx["persona"]
    labels = ctx.get("labels", [])
    outstanding = ctx.get("outstanding_reviewers", [])
    return f"""{_common_header(persona, ctx['action'])}
You are {persona}. Review PR #{pr} ({ctx.get('pr_title', '')}). Labels: {labels}.
Reviewers outstanding (you are first): {outstanding}.

## Step-by-step

**Step 1.** Read your persona prompt:
```bash
cat .github/agent-prompts/{persona}.md
```
**If file missing:** STOP. Post `PERSONA-REVIEW: {persona} REJECT — prompt file missing; trigger migrate_persona.` Exit.

**Step 2.** Fetch PR metadata:
```bash
gh pr view {pr} -R {REPO} --json title,body,labels,additions,deletions,files
```

**Step 3.** Read the diff:
```bash
gh pr diff {pr} -R {REPO}
```

**Step 4.** Apply your rubric. Produce in plain English:
   - One sentence: what the PR does.
   - Up to 3 concerns (each ≤120 chars).
   - Verdict: `APPROVE` or `REJECT`.

**Step 5.** Post using EXACT format (regex `^PERSONA-REVIEW: {persona} (APPROVE|REJECT)( — .*)?$`):

**Step 5a (APPROVE).**
```bash
gh pr comment {pr} -R {REPO} --body "PERSONA-REVIEW: {persona} APPROVE — <one-sentence rationale>"
```

**Step 5b (REJECT).**
```bash
gh pr comment {pr} -R {REPO} --body "$(cat <<'EOF'
PERSONA-REVIEW: {persona} REJECT — see concerns below.

- Concern 1: <text>
- Concern 2: <text>
- Concern 3: <text>
EOF
)"
```

**Step 6 (self-verification).**
```bash
gh pr view {pr} -R {REPO} --json comments --jq '.comments[-1].body' | head -1
```
**Expected first line matches regex:** `^PERSONA-REVIEW: {persona} (APPROVE|REJECT)`.

**Step 7.** If REJECT, also:
```bash
gh pr review {pr} -R {REPO} --request-changes --body "See PERSONA-REVIEW comment above."
```

## Common mistakes to avoid
- Do NOT write `LGTM`, `+1`, `nit:` — bot ignores them.
- Do NOT post two reviews. If you change your mind, post a new `PERSONA-REVIEW:` line — bot reads the LAST one.
- Stay in scope. If labels are outside your concern, APPROVE with rationale `out-of-scope for {persona}`.
- Do NOT use `<thinking>` tags or model-specific syntax.
"""


def render_address_changes(ctx: dict[str, Any]) -> str:
    pr = ctx["pr"]
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Lina (Implementer). PR #{pr} ({ctx.get('pr_title', '')}) is in CHANGES_REQUESTED. Address every concern.

## Step-by-step

**Step 1.** List every blocking comment:
```bash
gh pr view {pr} -R {REPO} --json reviews,comments --jq '
  [
    (.reviews[]   | select(.state=="CHANGES_REQUESTED") | {{author: .author.login, body: .body}}),
    (.comments[]  | select(.body|test("REJECT|CHANGES_REQUESTED")) | {{author: .author.login, body: .body}})
  ]'
```
**If empty:** STOP. PR state is stale; refresh and re-run.

**Step 2.** Check out the branch:
```bash
gh pr checkout {pr} -R {REPO}
```

**Step 3.** For EACH concern, make the smallest commit that addresses it. Conventional Commits:
```bash
git add <files>
git commit -m "fix(<scope>): address <reviewer>'s concern about <topic>"
```
**Do NOT pass `--no-verify`.**

**Step 4.** Run the gate locally:
```bash
composer check
```
**Must exit 0.** Fix and re-run if failing.

**Step 5.** Push:
```bash
git push --force-with-lease --force-if-includes
```
**Never plain `--force`.**

**Step 6.** Re-request reviews. For each rejecting `<P>`:
```bash
gh pr comment {pr} -R {REPO} --body "@<P> changes pushed, please re-review."
```

**Step 7 (self-verification).**
```bash
gh pr view {pr} -R {REPO} --json reviewDecision
```
**Expected:** `"reviewDecision":"REVIEW_REQUIRED"` or empty.

## Common mistakes to avoid
- Do NOT amend old commits — create NEW commits per concern. Audit trail needs them.
- Do NOT push red code. CI failure burns reviewer cycles.
- Conventional Commits scopes live in `.commitlintrc.json` — pick one that exists.
"""


def render_migrate_persona(ctx: dict[str, Any]) -> str:
    target = ctx.get("target_persona", "<persona-id>")
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Prism (PromptOps). Persona prompt for `{target}` is missing or stale. Migrate it.

## Step-by-step

**Step 1.** Confirm target's status:
```bash
ls -l .github/agent-prompts/{target}.md 2>/dev/null || echo "MISSING"
```

**Step 2.** Inspect a reference persona:
```bash
ls .github/agent-prompts/ | head -5
cat .github/agent-prompts/ari-orchestrator.md 2>/dev/null | head -40
```

**Step 3.** Create `.github/agent-prompts/{target}.md` with skeleton:
```markdown
# Persona: {target}

## Role
<one-paragraph role definition>

## Scope (labels this persona reviews)
- area:<x>
- risk:<y>

## Rubric (APPROVE requires)
1. <criterion 1>
2. <criterion 2>
3. <criterion 3>

## Verdict format
Post EXACTLY one comment per PR:
`PERSONA-REVIEW: {target} APPROVE — <rationale>` or
`PERSONA-REVIEW: {target} REJECT — see concerns below.`

## Out-of-scope guidance
If PR labels do not match Scope, APPROVE with rationale `out-of-scope for {target}`.
```

**Step 4.** Validate:
```bash
test -s .github/agent-prompts/{target}.md && echo OK || echo FAIL
```

**Step 5.** Commit on a new branch (NEVER on main):
```bash
git checkout -b chore/migrate-persona-{target}
git add .github/agent-prompts/{target}.md
git commit -m "chore(agent-prompts): migrate {target} persona prompt"
git push -u origin chore/migrate-persona-{target}
```

**Step 6.** Open PR:
```bash
gh pr create -R {REPO} \\
  --title "chore(agent-prompts): migrate {target}" \\
  --label "area:agent-governance" \\
  --body "Migrates the {target} persona prompt to current schema."
```

## Common mistakes to avoid
- Do NOT commit directly to `main`. Branch + PR.
- Do NOT omit `area:agent-governance` label — it triggers Prism + Mara as required reviewers.
"""


def render_implement_scenario(ctx: dict[str, Any]) -> str:
    sid = ctx.get("scenario", "<scenario-id>")
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Lina (Implementer). Scenario `{sid}` has no scorecard. Implement and score.

## Step-by-step

**Step 1.** Read scenario:
```bash
cat simulation/scenarios/{sid}.yml
```

**Step 2.** Probe chooser:
```bash
python simulation/tools/next_prompt.py --probe
```

**Step 3.** For each expected action, run:
```bash
python simulation/tools/next_prompt.py --emit-json
```
Compare to expected. Record PASS/FAIL.

**Step 4.** Create `simulation/scorecards/{sid}.json`:
```json
{{
  "scenario_id": "{sid}",
  "run_at_utc": "<YYYY-MM-DDTHH:MM:SSZ>",
  "steps": [
    {{"expected": "<action>", "actual": "<action>", "pass": true}}
  ],
  "verdict": "PASS",
  "notes": "<one paragraph>"
}}
```
Verdict is `PASS` only if every step's `pass` is `true`.

**Step 5.** Validate JSON:
```bash
python -c "import json; json.load(open('simulation/scorecards/{sid}.json')); print('OK')"
```

**Step 6.** Commit on branch:
```bash
git checkout -b feat/scenario-{sid}-scorecard
git add simulation/scorecards/{sid}.json
git commit -m "test(simulation): add scorecard for scenario {sid}"
git push -u origin feat/scenario-{sid}-scorecard
```

**Step 7.** Open PR with `area:agent-governance` label.

## Common mistakes to avoid
- Verdict MUST be `PASS` or `FAIL`. No other values.
- `run_at_utc` MUST be ISO-8601 with trailing `Z`.
- Do NOT edit scenario YAML to make test pass — fix the chooser.
"""


def render_retrospective(ctx: dict[str, Any]) -> str:
    days = ctx.get("days_since")
    days_text = f"{days} days ago" if days is not None else "never"
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Echo (Retrospective). Last retro was {days_text}. Cadence is {CADENCE_RETRO_DAYS} days.

## Step-by-step

**Step 1.** Last 7 days merged PRs:
```bash
gh pr list -R {REPO} --state merged --search "merged:>=$(date -u -d '7 days ago' +%F)" --json number,title,mergedAt,labels --limit 50
```

**Step 2.** Last 7 days closed Issues:
```bash
gh issue list -R {REPO} --state closed --search "closed:>=$(date -u -d '7 days ago' +%F)" --json number,title,closedAt,labels --limit 50
```

**Step 3.** Write retro using EXACT template (first line MUST be marker):
```
RETRO-LOG: window=last-7-days

### What went well
- <bullet>

### What hurt
- <bullet>

### Action items (each must name a persona)
- [ ] <action> — owner: <persona-id>

### Metrics
- PRs merged: <N>
- Issues closed: <N>
- CHANGES_REQUESTED cycles: <N>
```

**Step 4.** Post on Epic #{EPIC_ISSUE}:
```bash
gh issue comment {EPIC_ISSUE} -R {REPO} --body "$(cat retro-body.md)"
```

**Step 5 (self-verification).**
```bash
gh issue view {EPIC_ISSUE} -R {REPO} --json comments --jq '.comments[-1].body' | head -1
```
**Expected:** `RETRO-LOG: window=last-7-days`.

## Common mistakes to avoid
- Marker MUST be FIRST line. If later, scanner misses it.
- Action items MUST name a persona — `owner: someone` is invalid.
"""


def render_brainstorm(ctx: dict[str, Any]) -> str:
    days = ctx.get("days_since")
    days_text = f"{days} days ago" if days is not None else "never"
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Nova (Idea Generator). Last brainstorm was {days_text}. Cadence is {CADENCE_BRAINSTORM_DAYS} days.

## Step-by-step

**Step 1.** Read last 3 retros:
```bash
gh issue view {EPIC_ISSUE} -R {REPO} --json comments --jq '[.comments[] | select(.body|startswith("RETRO-LOG:"))][-3:]'
```

**Step 2.** Generate at least 5 ideas. Each:
```
- title: <≤80 chars>
  problem: <1 sentence>
  proposal: <1-2 sentences>
  effort: small | medium | large
  risk: low | medium | high
```

**Step 3.** Compose. FIRST line MUST be marker:
```
BRAINSTORM-LOG: ideas=<N>

<paste list from Step 2>
```

**Step 4.** Post:
```bash
gh issue comment {EPIC_ISSUE} -R {REPO} --body-file brainstorm-body.md
```

**Step 5 (self-verification).** First line of last comment matches `BRAINSTORM-LOG: ideas=<N>`.

## Common mistakes to avoid
- No `problem` field = idea rejected.
- Use EXACT tokens for effort/risk.
- Five is the floor.
"""


def render_meta_critique(ctx: dict[str, Any]) -> str:
    days = ctx.get("days_since")
    days_text = f"{days} days ago" if days is not None else "never"
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Prism (PromptOps). Last meta-critique was {days_text}. Cadence is {CADENCE_METACRITIQUE_DAYS} days.

## Step-by-step

**Step 1.** List all persona prompts:
```bash
ls -la .github/agent-prompts/
```
**Expected:** {len(PERSONAS)} `.md` files.

**Step 2.** Score each on clarity/rubric/format/scope (1-5).

**Step 3.** Sample 3 random merged PRs from last 30d:
```bash
gh pr list -R {REPO} --state merged --search "merged:>=$(date -u -d '30 days ago' +%F)" --json number --limit 50
```
For each, check whether persona reviews followed rubric.

**Step 4.** Compose. FIRST line MUST be marker:
```
META-CRITIQUE-LOG: prompts_audited=<N>

### Scores
| persona | clarity | rubric | format | scope |
|---|---|---|---|---|

### Rubric drift observed
- PR #<n>: <persona> approved without citing <criterion>

### Recommended fixes
- [ ] Update `.github/agent-prompts/<persona>.md` to clarify <X>
```

**Step 5.** Post on Epic #{EPIC_ISSUE}.

**Step 6 (self-verification).** Marker is FIRST line.

## Common mistakes to avoid
- Marker is `META-CRITIQUE-LOG:` — variations ignored.
- Score EVERY persona — drift hides in boring ones.
- Fixes MUST be actionable.
"""


def render_ari_triage(ctx: dict[str, Any]) -> str:
    reason = ctx.get("reason", "")
    return f"""{_common_header(ctx['persona'], ctx['action'])}
You are Ari (Orchestrator). No higher-priority action fired. Reason: {reason}

## Step-by-step

**Step 1.** Re-probe:
```bash
python simulation/tools/next_prompt.py --probe
```
**Expected:** `"action":"ari_triage"`. If different action: STOP, run that instead.

**Step 2.** Survey:
```bash
gh pr list -R {REPO} --state open --json number,title,labels,reviewDecision --limit 20
gh issue list -R {REPO} --state open --label "needs-triage" --json number,title --limit 20
```

**Step 3.** Pick ONE:
- Open PR with zero comments older than 24h → trigger `review_pr`.
- `needs-triage` Issue → assign labels + remove `needs-triage`.
- Neither → post heartbeat:
```bash
gh issue comment {EPIC_ISSUE} -R {REPO} --body "ARI-HEARTBEAT: board clear at $(date -u +%FT%TZ)."
```

**Step 4 (self-verification).** If heartbeat: first line of last comment is `ARI-HEARTBEAT:`.

## Common mistakes to avoid
- Do NOT invent work. Heartbeat + exit if queue clear.
- Do NOT post heartbeat more than once per 24h.
- Do NOT change PR labels as triage — they drive required reviewers.
"""


RENDERERS: dict[str, Any] = {
    "execute_merge": render_execute_merge,
    "sim_human_approval": render_sim_human_approval,
    "merge_gate": render_merge_gate,
    "review_pr": render_review_pr,
    "address_changes": render_address_changes,
    "migrate_persona": render_migrate_persona,
    "implement_scenario": render_implement_scenario,
    "retrospective": render_retrospective,
    "brainstorm": render_brainstorm,
    "meta_critique": render_meta_critique,
    "ari_triage": render_ari_triage,
}


def render_prompt(ctx: dict[str, Any]) -> str:
    action = ctx.get("action", "ari_triage")
    renderer = RENDERERS.get(action, render_ari_triage)
    return renderer(ctx)


def _state_to_dict(state: RepoState) -> dict[str, Any]:
    return {
        "open_prs": [
            {
                "number": pr.number, "title": pr.title, "labels": pr.labels,
                "mergeable": pr.mergeable, "review_decision": pr.review_decision,
                "ci_state": pr.ci_state,
                "has_rhea_approve": pr.has_rhea_approve,
                "has_sim_human_approve": pr.has_sim_human_approve,
                "has_changes_requested": pr.has_changes_requested,
                "persona_reviews_done": sorted(pr.persona_reviews_done),
            }
            for pr in state.open_prs
        ],
        "missing_personas": state.missing_personas,
        "stale_personas": state.stale_personas,
        "scenarios_without_scorecards": state.scenarios_without_scorecards,
        "days_since_retro": state.days_since_retro,
        "days_since_brainstorm": state.days_since_brainstorm,
        "days_since_metacritique": state.days_since_metacritique,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="next_prompt.py",
        description="Deterministic next-action chooser + dumb-model prompt renderer.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true", help="Print chooser decision + state summary (JSON).")
    group.add_argument("--emit", action="store_true", help="Print the full dumb-model prompt for the chosen action.")
    group.add_argument("--emit-json", action="store_true", help="Print decision + rendered prompt as JSON.")
    args = parser.parse_args(argv)

    state = gather_state()
    ctx = choose_action(state)

    if args.probe:
        payload = {"decision": ctx, "state": _state_to_dict(state)}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    prompt = render_prompt(ctx)

    if args.emit:
        print(prompt)
        return 0

    if args.emit_json:
        payload = {"decision": ctx, "state": _state_to_dict(state), "prompt": prompt}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
