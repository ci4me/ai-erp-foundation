# `simulation/` — the regression harness for persona prompts

This directory ships the **falsifiability layer** for the AI Agent Operating
Model. Every persona prompt change re-runs the scenarios here; any
regression blocks the PR via
[`.github/workflows/prompt-regression.yml`](../.github/workflows/prompt-regression.yml).

It exists because Prism (PromptOps) blocked
[ADR-001](https://github.com/ci4me/ai-erp-foundation/discussions/2) on the
ground that prompt changes without a regression gate are untested
mutations on live behavior. Issue #9 (Theme F) tracks the rollout.

## Layout

```
simulation/
├── README.md                   (this file)
├── requirements.txt            anthropic + pyyaml + jsonschema
├── run.py                      orchestrator — reads scenarios, dispatches personas, asserts verdicts
├── scenarios/
│   ├── _schema.yml             jsonschema for scenario YAML
│   └── 001-suspend-cookie.yml  first scenario (planted-flaw suspend command)
└── scorecards/                 (Phase 2) per-persona performance scorecards
    └── README.md
```

## Modes

`run.py` supports two modes:

| Mode | Trigger | Behavior | Cost |
| --- | --- | --- | --- |
| **`dry-run`** | No `ANTHROPIC_API_KEY` env var, or `--mode dry-run` flag | Validates scenario YAML against `_schema.yml`; lists personas that would be invoked; checks that all referenced personas exist under `.github/agent-prompts/`; **does not call Anthropic API**. Exits 0 on structure-only success. | $0 |
| **`live`** | `ANTHROPIC_API_KEY` set + `--mode live` flag (or omitted) | Dispatches each scenario's persona invocations via Anthropic API; asserts `expected_verdict` + `must_catch` flaws + zero hallucinations; emits a per-scenario PASS/FAIL report. | ~$0.05/scenario at Haiku, ~$0.30/scenario at Opus. |

The default in CI is **`dry-run`** until `ANTHROPIC_API_KEY` is configured
as a repo secret. Flipping to `live` is a one-issue follow-up.

## Adding a new scenario

1. Create `scenarios/NNN-name.yml` matching `scenarios/_schema.yml`.
2. Reference only personas that have a corresponding file under
   `.github/agent-prompts/<persona>.md`.
3. The next PR's `prompt-regression` workflow run validates the new
   scenario automatically.

## Scenario schema (excerpt)

See [`scenarios/_schema.yml`](scenarios/_schema.yml) for the full
jsonschema. Key fields:

```yaml
id: NNN-slug                   # unique scenario id
title: Human-readable title
description: One-paragraph context

mock_pr:                       # the simulated PR under review
  title: ...
  body: ...
  diff: |
    [unified diff text]

planted_flaws:                 # ground truth — agents do NOT see this list
  - id: F1
    name: short description
    severity: low | medium | high | critical
    detail: where in the diff the flaw lives

personas:                      # which personas are invoked
  - id: theo-architect
    expected_verdict: REQUEST_CHANGES
    must_catch: [F1, F2]       # MUST be caught for PASS
    may_catch: [F4]            # nice to have

expected_overall_verdict: BLOCKED   # from the synthesizing persona (Ari/Rhea)

pass_threshold:
  flaws_caught_pct: 70         # ≥70% of planted flaws must be caught across all personas
  hallucinations_allowed: 0
  per_persona_verdict_match: true   # every persona must match expected_verdict
```

## Pass / fail semantics

A scenario PASSES when:

1. `flaws_caught_pct` ≥ threshold (default 70 %).
2. `hallucinations_allowed` is not exceeded (default 0).
3. `per_persona_verdict_match` is satisfied (every persona's verdict equals `expected_verdict`).

Any failure blocks the PR. The workflow comment lists which scenarios
regressed and which personas drifted.

## Why this is the load-bearing piece

Without this harness, every persona prompt edit is an untested mutation
on the next 99 reviews. With it, the system has a falsification criterion:
"if you edit a prompt and the existing scenarios stop passing, your edit
broke something measurable." Theo (Architect) named falsification as the
single missing thing in v0.3 — this directory is it.
