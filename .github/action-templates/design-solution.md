---
id: design_solution
description: Propose a design for an issue before implementation
---

## Action: Design Solution for Issue #{{issue_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

```markdown
{{issue_body}}
```

## Steps

1. Restate the problem and the constraints in one short paragraph.
2. Propose the design: key components, data flow, and the smallest change that
   satisfies the acceptance criteria.
3. List alternatives considered and why they were rejected.
4. Call out risks, migrations, and rollback.

Do **not** open an implementation PR from this action — this is a design
proposal posted as an issue comment for review.

## Required output marker

End your posted comment with the machine-readable verdict so the loop knows
whether to proceed to implementation:

```
DESIGN-APPROVAL: APPROVE
```

Allowed values: `APPROVE`, `REQUEST_CHANGES`, `BLOCKED`. On `APPROVE` the loop
advances to `implement_issue`; otherwise it loops back for revision.
