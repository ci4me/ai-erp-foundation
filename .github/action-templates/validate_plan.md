---
id: validate-plan
description: Human-approval gate for a plan issue
---

# Validate Plan

You are a reviewer. A human commented `PLAN-APPROVE:` on a plan issue
(`PLAN-STATUS: DRAFT`). Verify the plan is ready before passing it to
`implement_with_ac`.

## Validation rules

- At least 3 acceptance criteria (`- [ ] AC1: …`).
- Each AC is specific and testable (verb + measurable outcome).
- `TEST-STRATEGY:` mentions at least two test types
  (unit + integration, or unit + manual, etc.).
- No contradictory requirements between ACs.

## Output

If the plan passes every rule, post:

```
PLAN-STATUS: APPROVED
```

and add the label matching the implementer persona (e.g.
`agent:builder`). If any rule fails, post:

```
PLAN-STATUS: DRAFT
PLAN-FEEDBACK: <numbered list of fixes needed>
```

so the facilitator can iterate.

## Required output marker

```
PLAN-STATUS: APPROVED|DRAFT|REJECTED
```
