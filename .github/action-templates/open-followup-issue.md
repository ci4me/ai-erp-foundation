---
id: open-followup-issue
description: Open a bounded follow-up issue
---

## Action: Open Follow-up Issue

Persona: {{persona_name}} (`{{persona_id}}`)

Open exactly one bounded issue with acceptance criteria, owner persona, risk label, source link, and what not to include.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
FOLLOWUP-ISSUE: OPENED
```

Allowed values: `OPENED`, `BLOCKED`.
