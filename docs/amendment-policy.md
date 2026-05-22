# Amendment Policy — Changes to the Operating Model Itself

**Status:** Accepted (Theme A of ADR-001 closure)
**Owner:** Vera, AI Risk Officer
**Effective:** immediately, applies to every PR that modifies `docs/operating-model.md`, `.github/agent-prompts/**`, `.github/workflows/governance-*.yml`, `.github/workflows/prompt-regression.yml`, or `simulation/**`

---

## Why this document exists

ADR-001 was author-classified `risk:medium`. Vera REQUEST_CHANGES'd on Discussion #2 (comment-17026075) because changes that **bind every future PR** are textbook `risk:high` per the v0.3 risk table — the author confused *current blast radius* with *forward blast radius*. A defective operating model silently mis-routes every future auth/audit/migration PR. Rollback cost is also under-stated: reverting one hour of YAML is cheap, but reverting 50 downstream PRs that were merged under unsound quorum rules is not bounded by the ADR's edit size.

This document closes the gap by stating, **mechanically and self-referentially**, that the operating model can only be amended through a specific gate. The gate applies to itself: amending this document is itself a `risk:high+` change.

---

## The rule

> **Any PR that modifies the operating model itself is `risk:high` at minimum and requires Architect + Risk Officer co-sign. No exceptions.**

"The operating model itself" means changes under any of:

- `docs/operating-model.md` (and any future split of it).
- `.github/agent-prompts/**` (any persona prompt, the preamble, or the README).
- `.github/workflows/governance-*.yml` (any of the split governance Actions).
- `.github/workflows/prompt-regression.yml` (the falsification gate).
- `simulation/**` (scenario YAML, schema, scorecards, harness code).
- This document.

The `risk-label.yml` Action will auto-assign `risk:high` to any PR touching these paths; downgrading is blocked by `governance-risk.yml` unless an override comment is posted by a CODEOWNER named in `.github/CODEOWNERS` for the affected path.

---

## Required reviewers (co-sign)

For any operating-model amendment PR:

| Persona | Required? | What they verify |
| --- | --- | --- |
| **Theo** (Architect) | YES — non-negotiable | Architectural soundness; the change doesn't break the persona contract, layer boundaries, or cloneability. |
| **Vera** (Risk Officer) | YES — non-negotiable | Risk classification is correct (this PR is itself at the right tier); rollback path is honest. |
| **Prism** (PromptOps) | YES if `.github/agent-prompts/**` is touched | The change doesn't degrade the regression-gate baseline. Re-run sims before approving. |
| **Iris** (Security) | YES if `.github/workflows/**` is touched | No new secret exposure, fork-bypass, or workflow-dispatch DoS. |
| **Rhea** (Release Manager) | YES — final merge gate | Quorum verified, all threads resolved. |
| **Human** (`@ci4me`) | YES — explicit "approved for operating-model amendment" comment | Honor-code maintainer sign-off; replaced by per-persona Apps in Phase 2. |

If any required reviewer is unavailable for 7+ calendar days, see the solo-dev escape valve in [`friction-budget.md`](./friction-budget.md) — the PR can NOT downgrade past `risk:high` for amendments, even if the friction budget would otherwise allow it.

---

## 30-day re-ratification clause

The operating model self-tests every 30 days.

On the 30th day after a major version (v0.3, v0.4, ...) lands on `main`, a scheduled GitHub Action opens an issue titled `Re-ratification window: operating model vX.Y` and pings every required-reviewer persona. The issue must close within 7 days with one of:

1. **Re-ratified** — Architect + Risk Officer + Human comment "still net-positive" with at least one cited metric from [`product-vision.md`](./product-vision.md) verdict criteria.
2. **Amended** — one or more amendment PRs opened to address discovered drift; re-ratification deferred until they land.
3. **Rolled back** — the version is officially declared net-negative; the rollback PR per the next section is opened.

A re-ratification window that closes with no decision auto-escalates to a `needs:human` issue and pings `@ci4me` directly.

---

## Rollback path

If re-ratification fails, or if any single PR demonstrates that the operating model produced a worse outcome than a 3-reviewer flat model would have:

1. Open a `risk:critical` PR titled `rollback: revert operating model to <prior version>`.
2. Required artifacts: the specific evidence (failed PR, missed audit finding, merged defect, cost overrun) that justifies rollback.
3. Required approvers: Theo + Vera + Iris + Omar + Rhea + Human.
4. The rollback reverts `docs/operating-model.md` to the prior version and disables the persona-activation Actions for 14 days while the team decides on the next iteration.
5. Open a sibling `work:retrospective` issue documenting why the version failed.

Rollback is reversible. A subsequent PR can restore the rolled-back version if new evidence emerges.

---

## Worked example: how this document classifies its own future amendments

**Scenario:** someone proposes adding a 33rd persona ("Drew, AI Database-Specific Risk Officer") to the catalog.

1. PR touches `.github/agent-prompts/drew-database-risk.md` (new file).
2. `risk-label.yml` Action auto-assigns `risk:high` (path matches `.github/agent-prompts/**`).
3. Required reviewers per this document: **Theo + Vera + Prism + Rhea + Human**. Iris not required (no `workflows/**` change). Omar not required (no `audit_log` schema change).
4. Theo verifies the new persona's frontmatter matches the contract, layer assignment is sound, doesn't duplicate an existing persona.
5. Vera verifies adding a persona is itself `risk:high` (not `risk:critical`, because rollback is cheap — just delete the file).
6. Prism verifies the new persona's prompt passes the existing regression scenarios.
7. Rhea checks quorum + threads.
8. Human posts "approved for operating-model amendment".
9. Merge.
10. The new persona enters the next 30-day re-ratification window's scope.

**Counter-scenario:** someone proposes lowering the `flaws_caught_pct` threshold from 70 % to 50 % in `simulation/scenarios/_schema.yml`.

This is **`risk:critical`**, not `risk:high`. Lowering the regression-gate threshold silently weakens every future prompt change. Required reviewers escalate to full critical quorum + 14-day comment period. Vera will block any attempt to downgrade this to `risk:high`.

---

## References

- ADR-001, Theme A — "Risk reclassification + self-amendment clause" (sub-issue #4)
- Discussion #2 comment-17026075 — Vera's REQUEST_CHANGES
- Discussion #2 comment-17026085 — Ari's synthesis, Theme A cluster
- Sibling documents: [`product-vision.md`](./product-vision.md), [`friction-budget.md`](./friction-budget.md)
- Future workflow: `risk-label.yml`, `governance-risk.yml` (TBD, Theme F)
