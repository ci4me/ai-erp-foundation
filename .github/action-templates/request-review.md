---
id: request_review
description: Formally request an additional reviewer on a PR
---

## Action: Request Review

Persona: {{persona_name}} (`{{persona_id}}`)

Request one additional reviewer — a named persona or a human — when the PR needs
an expertise lens that has not yet weighed in.

**Reason:** explain why this reviewer is needed.

## Required output marker

```
REVIEW-REQUEST: human
```

(Replace `human` with a persona id such as `iris-security` when requesting a
specific persona.)
