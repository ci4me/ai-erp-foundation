---
id: run-prompt-regression
description: Run simulation regression and post evidence
---

## Action: Run Prompt Regression

Persona: {{persona_name}} (`{{persona_id}}`)

```bash
python simulation/run.py --mode dry-run
python -m pytest simulation/tests || true
```

Post a signed summary with scenario pass/fail, missing personas, and cost if live mode was used.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
VALIDATION-RESULT: PASS
```

Allowed values: `PASS`, `FAIL`, `SKIPPED`.
