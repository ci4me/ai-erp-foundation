---
id: cost-review
description: Cost and budget review
---

## Action: Cost Review

Persona: {{persona_name}} (`{{persona_id}}`)

## Steps

1. Estimate per-run, monthly cron, and manual-dispatch worst case.
2. Distinguish target budgets from enforced budgets.
3. Recommend model tier, caching, ledger, and kill-switch changes.
4. Post signed cost verdict.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
COST-REVIEW: POSTED
```

Allowed values: `POSTED`, `BLOCKED`.
