# `.github/agent-prompts/` — canonical persona prompt source

This directory is the **single source of truth** for every persona's prompt.
It exists because Prism (PromptOps) blocked
[ADR-001](https://github.com/ci4me/ai-erp-foundation/discussions/2) on the
grounds that scattering prompts between the operating-model doc and ad-hoc
prompt files makes them unreviewable, unversioned, and untested.

## How agents know what to do — the full picture

This is the file-and-folder layout that answers "where does an AI agent look
to know how to behave in this repo":

```text
.github/
├── agent-prompts/              ← THIS DIRECTORY — canonical persona source
│   ├── README.md               (this file)
│   ├── _preamble.md            Universal Reviewer Preamble (all reviewer prompts include it)
│   ├── ari-orchestrator.md     Persona prompts — one per persona
│   ├── mara-product-owner.md
│   ├── vera-risk-officer.md
│   ├── theo-architect.md
│   ├── tessa-test-lead.md
│   ├── iris-security.md
│   ├── omar-audit.md
│   ├── rhea-release-manager.md
│   ├── cora-cost-architect.md
│   ├── prism-promptops.md
│   ├── echo-retrospective.md
│   └── ...                     (32 total when complete; current skeleton ships fewer)
├── workflows/                  ← Actions enforcing the model
│   ├── risk-label.yml          path-based risk classifier
│   ├── governance-risk.yml     per Theo: 3 single-responsibility checks, not 1 monolith
│   ├── governance-acceptance.yml
│   ├── governance-decision-record.yml
│   ├── prompt-regression.yml   per Prism: re-runs sim scenarios on prompt edits
│   ├── cost-telemetry.yml      per Cora: tokens & $ per persona run
│   └── header-validator.yml    per Iris: validates the structured comment header
├── ISSUE_TEMPLATE/             ← how to file work
│   ├── feature.yml
│   ├── bug.yml
│   ├── audit-finding.yml
│   ├── decision-record.yml
│   └── system-improvement.yml
├── pull_request_template.md    ← PR body schema (acceptance matrix + persona header)
└── CODEOWNERS                  ← path → required reviewer

docs/
├── operating-model.md          ← the v0.3 plan; describes the SYSTEM
└── personas/                   ← optional long-form docs per persona

simulation/
├── scenarios/                  ← per-scenario YAML; the sim harness re-runs these
│   ├── 001-suspend-cookie.yml
│   ├── 002-docs-only.yml
│   ├── 003-critical-migration.yml
│   └── 004-hallucination-trap.yml
└── scorecards/                 ← per Prism: persona quality scorecards
    └── <persona>.json          (clarity, FP rate, FN rate, token cost, sim-pass rate)

tools/
└── PHPStan/Rules/              ← mechanical checks born from the self-improvement loop

# GitHub-native (NOT folders, but where knowledge also lives):
# - Issues:      missions, epics, audit findings, remediation tickets
# - Discussions: ADRs, debates, dissent logs, retrospectives
# - Labels:      declarative triggers (risk:*, area:*, agent:*, audit:*)
# - Milestones:  phase tracking
# - Wiki:        Phase 3 — stable long-form playbooks (optional)
```

## Frontmatter contract (every persona file)

```yaml
---
id: theo-architect              # stable slug
name: Theo                       # display name
role: AI CQRS/DDD Architect
layer: engineering               # executive | engineering | assurance | knowledge
version: 0.1.0                   # semver; bump on any prompt change
model_default: claude-opus-4-7-1m
model_alternates:                # for cross-validation per v0.3 §14
  - claude-sonnet-4-6
lens: architecture
verdict_enum:                    # the only verdicts this persona may emit
  - APPROVE
  - APPROVE_WITH_CONDITIONS
  - REQUEST_CHANGES
  - COMMENT
  - ABSTAIN
activates_on:                    # label triggers (any match activates)
  - "area:domain"
  - "area:agent-governance"
  - "risk:high"
  - "risk:critical"
forbidden_paths:                 # this persona may not modify these
  - ".github/agent-prompts/**"   # no persona edits its own prompt
  - ".github/workflows/**"
context_pack: standard           # tiny | standard | deep | full-quorum
inherits_preamble: true          # auto-prepends _preamble.md
last_validated_against_model: claude-opus-4-7-1m
last_sim_pass: 2026-05-22         # date of last successful sim run
frozen_sha:                      # SHA at last sim pass (used by prompt-regression.yml)
owner: ci4me                     # who is accountable for this prompt
---
```

## Editing rules

1. **Every prompt edit is a PR.** No direct main edits.
2. **`prompt-regression.yml`** re-runs the 4 sim scenarios on any change here. PR cannot merge on regression.
3. **No persona may edit its own prompt.** Self-improvement proposals come from Prism (and even Prism's own prompt edits require Theo + human approval).
4. **Frontmatter `version` MUST bump** on any change. Patch for typos, minor for scope changes, major for verdict-enum or behavior overhauls.
5. **`frozen_sha`** is auto-updated by `prompt-regression.yml` when sims pass; never set manually.

## Currently shipped

This is the **Phase-0 skeleton.** It contains only:

- `_preamble.md` — Universal Reviewer Preamble (the 6 fixes from sim 004).
- `ari-orchestrator.md` — example executive persona.
- `theo-architect.md` — example engineering persona.

The remaining ~29 personas land via the existing roster in
[`docs/operating-model.md`](../../docs/operating-model.md) §2, on demand,
as Themes A–F from
[Discussion #2](https://github.com/ci4me/ai-erp-foundation/discussions/2)
close.

## Status

This file and the skeleton it documents are the beginning of **Theme B** from
the ADR-001 synthesis. Closing Theme B requires:

- [ ] All 32 personas migrated here with valid frontmatter.
- [ ] `_preamble.md` complete and referenced by every reviewer prompt.
- [ ] `prompt-regression.yml` workflow shipped and required.
- [ ] `simulation/scorecards/` schema defined.
- [ ] Universal Reviewer Preamble cross-linked from `docs/operating-model.md`.

When all five close, the Theme B sub-issue can close and ADR-001 may move
one step closer to `Approved`.
