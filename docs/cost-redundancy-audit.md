# Cost Redundancy Audit — personas dominated by deterministic gates

**Status:** Accepted (Theme C of ADR-001 closure)
**Owner:** Cora, AI Cost Architect
**Effective:** immediately; revisited at the 30-day re-ratification window

---

## Why this document exists

ADR-001 adopted a 32-persona catalog. Some of those personas exist for lenses
that an existing **deterministic** CI tool already covers perfectly — running
an LLM to re-render the same verdict is pure token waste. This audit names
those personas, demotes them from "LLM reviewer" to "Action observer," and
estimates the saved monthly spend.

The audit is path-driven and uses the projections Cora published on
[Discussion #2 comment-17026082](https://github.com/ci4me/ai-erp-foundation/discussions/2#discussioncomment-17026082):
~\$2.50–\$3.00 per PR for typical 5-persona review at Standard pack, scaling
to ~\$120–\$680/month at 5–20 PRs/week.

---

## Personas fully dominated by deterministic CI → demote

| Persona | Lens | Deterministic equivalent | Status |
| --- | --- | --- | --- |
| **Lex** | PHPStan L8 type / contract violations | `composer phpstan` (existing `composer check` gate) | **Demote** to Action observer — read PHPStan JSON output, comment on PR if non-empty, no LLM call |
| **Pico** | PHPCS / Slevomat style violations | `composer phpcs` + `phpcbf` auto-fix | **Demote** — Action observer |
| **Deck** | Deptrac layer-boundary violations | `vendor/bin/deptrac analyse --no-progress` | **Demote** — Action observer |
| **Doc** | Missing / drifting PHPDoc | `composer docblocks:audit` | **Demote** — Action observer |
| **Cliff** | Coverage threshold (90 %) | `phpunit --coverage-text` + `Generic.Metrics.MethodLength` etc. | **Demote** — Action observer |

For these 5 personas, the LLM was always re-rendering what PHPStan / PHPCS /
Deptrac / docblock-audit / coverage-report already prove. An "Action observer"
reads the deterministic tool's output, applies a tiny YAML-defined response
template (e.g. "PHPStan reports N errors — see workflow run"), and exits.
**Zero LLM tokens. Zero variance.**

**Estimated savings:** ~25–30 % of typical-PR cost (these 5 personas
collectively accounted for ~1.5 of every ~5 personas activated at
`risk:medium`). At 22 PRs/month × \$0.50 saved per PR = **~\$11/month at
typical volume; ~\$45/month at 20 PRs/week**. Not a fortune, but compounds with
the cap.

---

## Personas where LLM review IS load-bearing → keep

| Persona | Why keep |
| --- | --- |
| Theo (Architect) | Judgment on placement / cloneability / hidden coupling — no deterministic equivalent |
| Lina (Implementer) | Writes code; not a reviewer in the cost sense |
| Tessa (Test Lead) | Maps acceptance criteria → test evidence; non-deterministic |
| Iris (Security) | Threat modeling, prompt-injection, supply-chain reasoning |
| Omar (Audit) | Actor / correlation / audit_log semantic checks |
| Mara (Product Owner) | Acceptance-criteria fit — pure judgment |
| Vera (Risk Officer) | Risk classification on novel changes — judgment |
| Nova, Sofia, Kai, Pax | Domain-specific judgment, partial overlap with deterministic tools |
| Eve, Vale, Hex, Quinn, Bus, Saga | DDD / event / VO / boundary judgment — no equivalent gate |
| Rhea (Release) | Multi-input synthesis — irreducibly LLM |
| Milo, June, Echo, Prism, Cora | Knowledge / process — not per-PR review |

---

## Personas with PARTIAL overlap → tier them

These keep their LLM lens but get **demoted to Haiku** (cheap tier) unless the
PR carries `risk:high` or `risk:critical`:

| Persona | Default model | Reason |
| --- | --- | --- |
| Nova (API) | Haiku — most API checks are mechanical (status codes, content types) | Upgrade to Sonnet on `area:api` + `risk:high+` |
| Sofia (Frontend/UX) | Haiku — most UI changes are visual review-able | Upgrade to Sonnet on `area:auth` + `area:frontend` combo |
| Kai (DevOps) | Haiku — most Action changes are template-y | Upgrade to Sonnet on `area:ci` + `risk:high+` |
| Pax (Performance) | Haiku — most performance regressions are caught by load tests | Upgrade to Sonnet on `area:database` + new query |

**Estimated savings:** another ~15–20 % at typical mix.

---

## Combined budget impact

| Volume | Pre-audit projection | Post-audit projection |
| --- | --- | --- |
| 5 PRs/week typical | \$120–170/month | **\$70–110/month** |
| 20 PRs/week typical | \$480–680/month | **\$280–440/month** |
| 5 PRs/week, 20 % critical | (same as above) | (full-quorum critical PRs unchanged — those need every lens) |

Roughly **35–40 % reduction** for the typical case. Critical-risk PRs are
unaffected because Theo + Iris + Omar + the human are all judgment lenses
that can't be demoted.

---

## Action items (tracked separately)

- [ ] Sub-issue **#21** — implement "Action observer" `mode` in persona
      activation; persona files gain a `mode: observer | reviewer` frontmatter
      field; backing code in `simulation/_live.py` routes `mode: observer`
      personas to a deterministic adapter instead of an LLM dispatch.
- [ ] Sub-issue **#21** (same) — update `.github/agent-prompts/<persona>.md`
      frontmatter for Lex / Pico / Deck / Doc / Cliff to `mode: observer`.
- [ ] Sub-issue (TBD) — tier Nova / Sofia / Kai / Pax to Haiku-by-default
      with escalation rules.
- [ ] Sub-issue (TBD) — re-baseline after first 10 live runs; compare the
      35–40 % savings projection to measured spend on the cost-telemetry
      tracking issue (#19).

---

## References

- [Discussion #2 comment-17026082](https://github.com/ci4me/ai-erp-foundation/discussions/2#discussioncomment-17026082) — Cora's original deliberation
- [`docs/friction-budget.md`](./friction-budget.md) — persona-activation matrix this audit complements
- [`docs/amendment-policy.md`](./amendment-policy.md) — promoting a demoted persona back to LLM is itself `risk:high`
- [`.github/workflows/cost-telemetry.yml`](../.github/workflows/cost-telemetry.yml) — the weekly rollup that makes this auditable
- [`simulation/cost_rollup.py`](../simulation/cost_rollup.py) — the rollup logic
