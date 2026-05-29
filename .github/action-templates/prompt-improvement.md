---
id: prompt-improvement
description: Patch a persona prompt or preamble after evidence of prompt weakness
---

## Action: Prompt Improvement

Persona: {{persona_name}} (`{{persona_id}}`)

Source issue: #{{source_issue_number}} - {{source_issue_title}}

## Steps

1. Cite the exact simulation, review, or incident that proves a prompt weakness.
2. Patch the smallest prompt text that fixes that weakness.
3. Bump the prompt version.
4. Run prompt regression.
5. Open a `risk:high` operating-model amendment PR.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
PROMPT-PATCH: PR_OPENED
```

Allowed values: `PR_OPENED`, `BLOCKED`.
