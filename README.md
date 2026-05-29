# ai-erp-foundation

An autonomous, GitHub-native ERP foundation experiment. The repository is not
only an application scaffold; it is also an operating model for an AI-agent team
that can triage issues, review pull requests, manage discussions, validate its
own outputs, and continue work by reading GitHub state.

## Core idea

GitHub is the state machine. Issues, PRs, reviews, comments, discussions, and
milestones are the durable memory of the AI team. Agents do not rely on private
chat context. They run:

```bash
python3 -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --output /tmp/next.md
```

Then they execute exactly one rendered prompt. The result they post must be
signed and include a machine-readable marker such as `REVIEW-VERDICT:` or
`ACCEPTANCE-DECISION:`. The next run reads that marker and moves the loop
forward.

## Important files

```text
.github/action-templates/catalog.yml     Action menu and priorities
.github/action-templates/markers.yml     Machine-readable state markers
.github/action-templates/*.md            Prompt templates for each action
.github/agent-prompts/*.md               Persona behavior and capabilities
simulation/tools/next_prompt.py          Chooses and renders the next action
simulation/tools/agent_output_validator.py
simulation/tools/marker_registry.py
simulation/tools/agent_event_guard.py
scripts/run_planner.py                   Deterministic planner entry point
simulation/tools/persona_registry.py     Dynamic persona discovery
simulation/tools/state_fetcher.py        GitHub state snapshot
simulation/tools/state_analyzer.py       Rule-based problem detection
simulation/tools/plan_builder.py         Builds single/multi-step plans
simulation/tools/plan_executor.py        Executes (or dry-runs) plans
simulation/tests/                       Regression and coverage tests
```

## Run locally

```bash
python3 -m pytest -q
python3 -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --probe-only
python3 -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --post-mode dry-run --output /tmp/next.md
```

For live runs, `next_prompt.py` first tries authenticated `gh`. If `gh` is not available it falls back to read-only GitHub REST/GraphQL calls using `GITHUB_TOKEN`/`GH_TOKEN` when present. In a no-network sandbox, use the fixture bridge:

```bash
python3 -m simulation.tools.run_next_prompt_from_fixture \
  --fixture /tmp/github-state.json \
  --repo ci4me/ai-erp-foundation \
  --post-mode dry-run \
  --output /tmp/next.md
```

Run the full static coverage audit with:

```bash
python3 -m simulation.tools.action_coverage
```

## Autonomous planner

`scripts/run_planner.py` is a deterministic, LLM-free planner that reads live
GitHub state, detects problems with a pure-Python rule engine, and assigns each
fix to a persona discovered dynamically from `.github/agent-prompts/*.md` (no
hardcoded persona ids — ownership is derived from each persona's frontmatter
`actions` list).

It has two independent axes:

- **mode** — `single` resolves the single highest-priority problem (one action
  per run); `multi` resolves every detected problem in one pass.
- **apply** — the planner is **dry-run by default**; it prints exactly what it
  would do and mutates nothing. Pass `--apply` (or `PLANNER_APPLY=1`) to execute.

```bash
# Dry-run the highest-priority action (safe default):
python3 scripts/run_planner.py

# Dry-run the full multi-step plan:
python3 scripts/run_planner.py --mode multi

# Execute one action for real:
python3 scripts/run_planner.py --mode single --apply
```

Pipeline: `state_fetcher` → `state_analyzer` → `plan_builder` → `plan_executor`,
configured by `simulation/tools/config.py`. Detected problem types, in priority
order: **unanswered persona requests**, empty PRs (no source files), issues
missing required markers, trivial issues with no PR, unreviewed PRs, and stale
plan-request discussions.

### Persona request system

A persona can pull others into the loop by adding a marker to an issue/PR body:

```text
REQUEST-REPLY-FROM: @mara-product-owner, @tessa-test-lead
REQUEST-REVIEW-FROM: @theo-architect
REQUEST-APPROVAL-FROM: @vera-risk-officer
QUESTION-TO: @iris-security? Is this endpoint safe?
```

These become the highest-priority problem (`UNANSWERED_REQUEST`), and the
planner generates one reply/review action per *known* persona that has **not
yet responded** — so re-running never double-posts. Only handles matching a
real persona id are honored; free text after a `QUESTION-TO:` is ignored.

### Debug logs

Every executed (or dry-run) step is written to
`logs/YYYY-MM-DD/<run_id>-step-<NNNN>.json` by
`simulation/tools/debug_logger.py` (persona, action, target, prompt body, the
exact `gh` command, its output, success/error, and the dry-run flag). The
console shows one summary line per step; the `logs/` directory is gitignored.

```bash
ls logs/$(date +%Y-%m-%d)/
cat logs/$(date +%Y-%m-%d)/*-step-0001.json | jq '.'
```

### Collaboration, epics, and phase lifecycle

Beyond the linear `create_issue → triage → implement → review → merge` flow, the
planner supports richer team behaviors (all driven by markers documented in
[Markers and validation](docs/markers-and-validation.md)):

- **Collaboration** — personas debate (`ARGUMENT`/`COUNTER-PROPOSAL`), clarify
  (`REQUEST-INFO`/`RESPONSE`), decide (`RESOLUTION`, multi-persona
  `CONSENSUS-REACHED`), and escalate deadlocks (`OBJECTION`/`ESCALATION`).
- **Epic decomposition** — an `epic`-labeled issue is broken into `SUB-TASK`s via
  a `DECOMPOSITION-PLAN`, with `Depends on: #n` dependency gating.
- **Phase lifecycle** — epics advance through
  `phase/planning → implementation → testing → acceptance → done`, gated on each
  phase's exit criteria, with human approval at the Planning and Acceptance gates.

The deterministic audit covers all of this:

```bash
python3 simulation/tools/full_audit.py
```

## Documentation map

- [Autonomous loop runbook](docs/autonomous-loop.md)
- [Markers and validation](docs/markers-and-validation.md)
- [Action coverage](docs/action-coverage.md)
- [Independent agent drill](docs/independent-agent-drill.md)
- [Code maintenance notes](docs/code-maintenance.md)
- [Operating model](docs/operating-model.md)

## Team request start point

A human request like “Build a new feature to export paid invoices as CSV” should enter GitHub as an Issue or Discussion body with an explicit marker:

```text
TEAM-REQUEST: Build a new feature to export paid invoices as CSV.
```

The next loop selects `create_issue`, creates one bounded `needs-triage` issue, then proceeds through `triage_issue -> implement_issue -> review_pr -> merge_gate -> accept_pr -> merge_pr -> close_issue`.

## Safety rule

The loop may be autonomous, but it is not allowed to trust prose. Every mutation
must be preceded by validation and followed by a marker-bearing, signed result.

## Acknowledgement

This project is an autonomous-loop achievement: every change reaches main via a signed, marker-bearing PR.
