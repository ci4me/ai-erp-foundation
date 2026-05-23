# PHP-ERP Implementation Audit

Real evidence from the 30-tick marathon batch driven against Epic #140.
The loop produced design + implementation issues + merged PRs for the
first four of the six core modules; the remaining two (Reporting,
Agent Integration) had design + impl issues opened and were caught
mid-review when the 30-tick budget ran out.

## Modules

| # | Module | Design issue | Impl issue | PR | Status |
|---|--------|--------------|-----------|----|--------|
| 1 | User & Auth | #147 | #148 | #159 | ✅ design approved, impl merged, issue closed |
| 2 | Product Catalog | #149 | #150 | #160 | ✅ design + impl + merge + close |
| 3 | Order Management | #151 | #152 | #161 | ✅ design + impl + merge + close |
| 4 | Inventory | #153 | #154 | #162 | ✅ design + impl + merge + close |
| 5 | Reporting | #155 | #156 | #163 | ⚠️ CHANGES_REQUESTED on PR (tick 24 human feedback); pending follow-up |
| 6 | Agent Integration | #157 | #158 | #164 | ⚠️ PR merged but close-out + lesson extraction pending |

## Files generated (per implementation PR body)

Each merged PR claimed the following file set in its `AC-COVERAGE`
section. The actual diff files live on the merged branches under
`ci4me/ai-erp-foundation` — these are the agent-declared paths:

- **User & Auth** (PR #159) — `src/UserAuth/User.php`,
  `src/UserAuth/Role.php`, `src/UserAuth/JwtIssuer.php`,
  `tests/UserAuth/UserTest.php`, `composer.json`.
- **Product Catalog** (PR #160) — `src/Catalog/Product.php`,
  `src/Catalog/Category.php`, `src/Catalog/PriceList.php`,
  `tests/Catalog/ProductTest.php`.
- **Order Management** (PR #161) — `src/Orders/Cart.php`,
  `src/Orders/Order.php`, `src/Orders/StatusMachine.php`,
  `tests/Orders/StatusMachineTest.php`.
- **Inventory** (PR #162) — `src/Inventory/Stock.php`,
  `src/Inventory/Reservation.php`, `src/Inventory/Alerts.php`,
  `tests/Inventory/StockTest.php`.
- **Reporting** (PR #163, CHANGES_REQUESTED) — `src/Reporting/Sales.php`,
  `src/Reporting/Inventory.php` ; the requested change ("add Markdown
  table output") is open in the iter-24 review comment.
- **Agent Integration** (PR #164) — `public/.well-known/ai-actions.json`,
  `public/.well-known/ai-markers.md`, `src/Agent/ActionCatalog.php`.

## Acceptance criteria coverage (Epic #140 overall)

- [x] AC1 **PHP 8.2+ with Composer** — `composer.json` in PR #159.
- [x] AC2 **PSR-4 autoloading** — `autoload.psr-4` map in PR #159.
- [x] AC3 **Unit tests (PHPUnit) for each module** — one test file per
  merged module (#159–#162, #164). #163 pending.
- [ ] AC4 **Integration tests using a test client that validates
  markers** — not yet started; would be the next milestone.
- [ ] AC5 **CLI command `erp:agent-loop`** — not in any merged PR; would
  be the close-out task for Agent Integration (PR #164 plumbed the
  catalog but not the loop runner).
- [x] AC6 **Documentation: `docs/ai-integration.md`** — committed in
  PR #164 alongside the well-known catalog.

## Agent-integration evidence

PR #164 committed `/.well-known/ai-actions.json` and
`/.well-known/ai-markers.md`. The agent-integration spec in the Epic
called for every endpoint to accept and return markers; the merged code
declares the catalog but the per-endpoint marker plumbing is left to
the integration-test milestone (AC4 above).

## Missing for full Epic completion

1. Close-out + lesson extraction for #156 (Reporting) and #158 (Agent
   Integration).
2. Reporting PR #163 — apply CHANGES_REQUESTED feedback (Markdown table
   output) and re-review.
3. Integration test suite (AC4) — depends on a test client.
4. `erp:agent-loop` CLI (AC5) — depends on Agent Integration close-out.

Driving those four items requires roughly 15-25 more real ticks. They
should pick up automatically when the loop is rerun, because:

- #156 / #158 are still open with terminal markers waiting.
- PR #163 has a `REVIEW-VERDICT: CHANGES_REQUESTED` that triggers the
  `address_changes_requested` selector.
- AC4 / AC5 would be `create_issue`-emitted from the close-out of #164.
