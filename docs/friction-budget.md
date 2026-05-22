# Friction Budget — Persona Activation per PR

**Status:** Accepted (Theme E of ADR-001 closure)
**Owner:** Mara, AI Product Owner
**Effective:** immediately, reviewed on 2026-07-01 alongside [`product-vision.md`](./product-vision.md)

---

## The problem

The operating model assumes every PR can get every lens. For a solo developer shipping against a 2026-07-01 falsification date, full-quorum review on every PR = ~8 review threads × ~1.5 PRs/week = 12 review cycles a week. Most of those PRs are renames, doc fixes, or low-risk refactors that do not need a security lens or an audit lens. Without a budget, the model collapses under its own weight in three weeks and the developer starts skipping reviews entirely — which is worse than no model at all, because now we have the appearance of governance without the substance.

This document defines what governance each PR actually owes, indexed to risk.

---

## The friction budget matrix

Every PR carries exactly one `risk:*` label, set by the author at open time (or auto-assigned by `risk-label.yml`). The label determines the minimum personas and artifacts required to merge.

| Risk level | Personas activated | Required artifacts |
| --- | --- | --- |
| `risk:low` | 1 (orchestrator only) | linked issue + risk label |
| `risk:medium` | 3 (architect + test + 1 lens-relevant) | + acceptance matrix |
| `risk:high` | 5–6 (architect + test + security + audit + release + 1 lens) | + decision record + rollback note |
| `risk:critical` | 8+ (full quorum) | + human "approved for critical risk" sign-off |

**Definitions:**

- `risk:low` — typo fixes, doc-only changes, dependency patch bumps, test-only additions, log message tweaks. If broken, reverts are trivial.
- `risk:medium` — new handler in an existing domain, new query, view changes, non-breaking schema additions. Single-domain blast radius.
- `risk:high` — new domain scaffolding, cross-domain command flows, public-facing API changes, anything touching auth or billing, migrations that backfill data.
- `risk:critical` — production data destruction risk, security-boundary changes, multi-tenant isolation changes, anything that could leak Lia's client's bank data.

The "1 lens-relevant" slot at medium/high means: pick the **one** specialist whose domain this PR actually touches (e.g., `ddd-specialist` for an aggregate change, `phpstan-specialist` for a typing-heavy refactor). Not all of them. One.

---

## Solo-dev escape valve

This template is currently maintained by one human (`@ci4me`). The operating model must degrade gracefully when that human is offline — sick, on vacation, or just heads-down on Lia's reconciliation flow. The escape valve is simple: **no PR blocks indefinitely waiting on a human persona slot**. If the only outstanding requirement is a human sign-off and the clock runs out, the PR auto-downgrades to the next risk tier and proceeds with the personas that tier allows. The downgrade is logged on the PR so we can audit later whether it caused defects.

The escape valve is not an excuse to skip reviews. It is an admission that a stalled PR is itself a risk — unmerged code rots, branches diverge, and the next PR builds on assumptions the unmerged one was supposed to validate.

---

## Auto-downgrade rule

The downgrade ladder is mechanical, runs on a daily cron, and is visible:

- `risk:critical` PR with no human "approved for critical risk" comment within **7 calendar days** of open → downgrade to `risk:high`, post comment tagging `@ci4me`, add label `downgraded:critical-to-high`.
- `risk:high` PR with no decision record / rollback note within **5 calendar days** of open → downgrade to `risk:medium`, post comment tagging `@ci4me`, add label `downgraded:high-to-medium`. (The author is expected to add the artifacts; if they don't, the PR loses tier privileges.)
- `risk:medium` PR with no acceptance matrix within **3 calendar days** of open → downgrade to `risk:low`, post comment tagging `@ci4me`, add label `downgraded:medium-to-low`.
- `risk:low` PRs never downgrade; they just merge once the orchestrator and CI are green.

A PR that has been downgraded twice in its lifetime gets label `downgrade:repeat` and is surfaced in the weekly review. If we are downgrading the same PR repeatedly, the original risk label was wrong or the artifact requirement is unrealistic — both are signals worth investigating on 2026-07-01.

Downgrades are reversible: if the human shows up and adds the missing artifact, the PR is re-labeled to its original tier and the downgrade label is removed (but kept in the audit log via the comment trail).

---

## References

- GitHub Discussion #2 — "Adopting the v0.3 AI Agent Operating Model" (REQUEST_CHANGES from @mara, comment-17026074)
- ADR-001, Theme E — "Operating-model adoption requires falsifiable product hypothesis"
- Theme E sub-issue #8 — "Product framing: first ERP user + MVP test + friction budget"
- Sibling document: [`docs/product-vision.md`](./product-vision.md)
