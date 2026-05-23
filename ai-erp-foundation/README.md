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
