# Action: phase_gate

You are the system. Epic #{{ issue_number }} has completed phase
`{{ current_phase }}` and is ready to advance to `{{ next_phase }}`.

Confirm the exit criteria for the current phase are met:

- **Planning → Implementation:** `CONSENSUS-REACHED` (or `RESOLUTION`) present,
  a `DECOMPOSITION-PLAN` present, and `ACCEPTANCE-DECISION: Approved` from the
  requested approver (if a `REQUEST-APPROVAL-FROM` gate was posted).
- **Implementation → Testing:** every child sub-task issue is closed, and each
  met its Definition of Done (≥1 approving review, no open objections).
- **Testing → Acceptance:** a `TEST-REPORT: Pass` is present.
- **Acceptance → Done:** `ACCEPTANCE-DECISION: Approved` from the product owner.

If the criteria are met, apply the `{{ next_phase }}` label, remove the
`{{ current_phase }}` label, and post:

```
PHASE-CHANGE: {{ current_phase }} -> {{ next_phase }} (reason: exit criteria met)
```

If the criteria are not met, do nothing. Sign your post with the persona header.
