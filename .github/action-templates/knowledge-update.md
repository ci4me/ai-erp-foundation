---
id: knowledge-update
description: Turn a stable lesson into durable knowledge
---

## Action: Knowledge Update

Persona: {{persona_name}} (`{{persona_id}}`)

Extract only stable lessons from merged work or repeated findings. Patch the canonical doc, Discussion, or wiki target and cite source evidence.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
KNOWLEDGE-UPDATE: PR_OPENED
```

Allowed values: `PR_OPENED`, `BLOCKED`.
