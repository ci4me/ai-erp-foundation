---
id: promote-idea
description: Promote an Idea Lab Discussion to an Issue
---

## Action: Promote Idea

Persona: {{persona_name}} (`{{persona_id}}`)

Verify the reaction gate, maintainer signal, duplicate status, and product fit. If promoted, create a feature Issue and comment back on the Discussion.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
IDEA-PROMOTION: ISSUE_OPENED
```

Allowed values: `ISSUE_OPENED`, `BLOCKED`.
