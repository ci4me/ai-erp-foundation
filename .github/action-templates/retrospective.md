---
id: retrospective
description: Retrospective after failed, reverted, stalled, or repeated-defect work
---

## Action: Retrospective

Persona: {{persona_name}} (`{{persona_id}}`)

Classify the failure as check gap, prompt gap, doc gap, product gap, cost gap, or human-process gap. Recommend the smallest next action.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
RETRO-FINDING: POSTED
```

Allowed values: `POSTED`.
