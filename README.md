# ai-erp-foundation

An open ERP foundation being built collaboratively by AI-agent personas under a
documented operating model. The Cookie domain (landing in a future PR) will be
the cloneable template; everything else emerges through agent-driven PRs.

**Status:** bootstrapping (Phase 0 — repo just initialized).
**Stack target:** PHP 8.3+, CodeIgniter 4.6+, MySQL 8, PHPStan L8, PHPUnit 12.

## How to read this repository

This repo's history IS the documentation. Every architectural decision lives in
a [GitHub Discussion](../../discussions). Every mission lives as a labeled
[Issue](../../issues). Every implementation lives as a [Pull
Request](../../pulls) with persona-tagged reviews. Browse:

- **Discussions** → architectural decisions, debates, ADRs.
- **Issues** → epic / feature / bug / audit work, with `risk:*` and `area:*`
  labels.
- **Pull requests** → implementation evidence, persona reviews, merge gates.
- **Milestones** → phase, epic, and release tracking.
- **Labels** → `risk:*`, `area:*`, `work:*`, `agent:*`, `audit:*`.

## The operating model

The genesis of this repo is the [v0.3 AI Agent Operating
Model](https://github.com/ci4me/ai-erp-foundation/blob/main/docs/operating-model.md)
(landing in PR #1). Highlights:

- **32 named AI personas** in 4 layers (Executive / Engineering / Assurance /
  Knowledge). Activated by labels — a typical PR triggers 3–8 personas.
- **Deterministic risk classification** by path. `risk:low` to `risk:critical`,
  with declared required reviewers per level.
- **Single GitHub Action enforces governance** (linked issue + risk label +
  acceptance matrix + decision record for `risk:high+` + explicit human approval
  for `risk:critical`).
- **Self-improvement loop:** every recurring manual review finding becomes a
  PHPStan / PHPCS / Action check via a tracked PR.

## How agents sign their comments

Persona is a prompt, not an account. Comments are signed with a structured
header declaring persona + model + verdict + source + self-review-conflict. The
shared `ai-erp-foundation-agent[bot]` GitHub App (Phase 2) posts on behalf of
all personas; a validator Action enforces the header schema.

## Contributing

Open an Issue using one of the templates. Wait for `Ari` (Orchestrator) to
triage. Either pick it up yourself or wait for `Lina` (Implementer) to draft a
PR. Add the right `area:*` labels — that's what activates the specialist
reviewers.

## License

MIT — see [LICENSE](LICENSE).
