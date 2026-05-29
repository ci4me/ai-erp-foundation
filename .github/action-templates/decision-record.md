---
id: decision-record
description: Post a compact decision record
---

## Action: Decision Record

Persona: {{persona_name}} (`{{persona_id}}`)

Use the operating-model compact template: Decision, Why, Rejected alternatives, Risk if wrong, Rollback, Approver.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
DECISION-RECORDED: POSTED
```

Allowed values: `POSTED`.
