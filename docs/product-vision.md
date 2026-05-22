# Product Vision — First ERP User & Falsification Test

**Status:** Accepted (Theme E of ADR-001 closure)
**Owner:** Mara, AI Product Owner
**Falsification date:** 2026-07-01

---

## Why this document exists

We adopted an 8-persona AI operating model before defining who the ERP is for or what it does. That is backwards. This document fixes the order: pick a user, pick a capability, pick a date, and decide in advance what evidence will tell us the operating model is paying for itself.

If the metrics in this doc are red on 2026-07-01, we cut personas, not deadlines.

---

## First ERP user

**Lia, a solo bookkeeper running her own micro-practice serving 12–20 small Brazilian retail clients (padarias, salons, neighborhood shops).** She works from her apartment, charges a monthly retainer per client, and currently glues together a spreadsheet, a WhatsApp folder, and her bank's CSV export. She loses roughly half a day per client per month to reconciling sales receipts against bank deposits, and she turns down new clients because onboarding a new spreadsheet template costs her a full Saturday.

We picked Lia (not a small-business owner, not a school administrator) for three reasons. First, her pain is reconciliation — a workflow we can model with the CQRS patterns already in this template without inventing new infrastructure. Second, she pays for software today (she already buys a R$ 80/month accounting tool she hates), so willingness-to-pay is proven. Third, her feedback loop is fast: she touches the tool daily and will tell us within a week if something is broken or useless. A small-business owner would log in twice a month; a school admin would need procurement approval. Lia ships faster.

---

## First capability

**Bank-statement-to-receipt reconciliation for a single client account.** Lia uploads a CSV from her client's bank, the system shows unmatched debits/credits next to a list of unreconciled sales receipts she has already entered, and she can match them one-click or flag them for follow-up. That is the entire MVP. No invoicing, no tax calculation, no multi-tenant billing — one bookkeeper, one client account, one CSV, one reconciliation screen.

Scope is intentionally tiny so we can ship in 4–6 weeks against the existing Cookie-domain reference architecture. The capability is concrete enough that we can demo it to Lia on 2026-07-01 and watch her either reconcile a real client's June statement faster than her spreadsheet, or struggle and abandon. Either outcome is informative.

---

## Operating-model verdict criteria

On 2026-07-01 we judge the operating model against the following. The model is **net-positive** only if 4 of 5 metrics hit target. Otherwise we trigger the friction-budget downgrade (see `friction-budget.md`).

| Metric | Target on 2026-07-01 | Measurement method |
| --- | --- | --- |
| PRs merged to `main` since 2026-04-01 | ≥ 18 (avg 1.5/week) | `gh pr list --state merged --base main --search "merged:>=2026-04-01"` |
| Median time-to-merge (PR open → merged) | ≤ 72 hours | GitHub PR timeline export, median across all merged PRs in window |
| Defect escape rate (bugs found post-merge / PRs merged) | ≤ 15 % | Count issues opened with `type:bug` referencing a merged PR in window |
| Lia's reconciliation task time (vs. spreadsheet baseline) | ≥ 30 % faster on her June 2026 statement | Timed session on 2026-07-01, baseline measured 2026-04-15 |
| Solo-dev hours/week spent responding to persona reviews | ≤ 6 hours | Self-reported time log, sampled weekly |

If PRs merged < 18 OR time-to-merge > 72h, the operating model is slowing us down regardless of code quality. If Lia is not ≥ 30 % faster, the capability is wrong and persona quality didn't save us. If solo-dev hours > 6/week, the model is unsustainable.

---

## Out of scope (explicitly NOT shipping by 2026-07-01)

- Multi-tenant SaaS billing, user accounts, password resets — Lia uses one local install.
- Invoice generation, tax calculation, NFe / NFCe integration — pure reconciliation only.
- Bank API / Open Finance integration — manual CSV upload is the contract.
- Mobile app, PWA, offline mode — desktop browser only.
- More than one bookkeeper, more than one client per install — Lia + one client account.
- Any persona, capability, or workflow not directly required to reconcile a June 2026 CSV against entered receipts.

If a PR introduces work outside this list before 2026-07-01, it is rejected on scope alone regardless of code quality.

---

## References

- GitHub Discussion #2 — "Adopting the v0.3 AI Agent Operating Model" (REQUEST_CHANGES from @mara, comment-17026074)
- ADR-001, Theme E — "Operating-model adoption requires falsifiable product hypothesis"
- Theme E sub-issue #8 — "Product framing: first ERP user + MVP test + friction budget"
- Sibling document: [`docs/friction-budget.md`](./friction-budget.md)
