# Action: rework_from_rejection

You are the system. Epic #{{ issue_number }} was blocked at acceptance by a human:

```
ACCEPTANCE-DECISION: Blocked (reason: {{ reason }})
```

Route the epic back to the appropriate phase so the team can address the
rejection. The planner has pre-computed the target phase as **{{ target_phase }}**.

Steps:

1. Read the rejection reason from the `ACCEPTANCE-DECISION` comment.
2. Confirm the target phase against the reason:
   - scope / design / requirements → `phase/planning`
   - implementation quality / code → `phase/implementation`
   - test coverage / bugs → `phase/testing`
   - unclear → `phase/planning` (and ask `REQUEST-INFO:`)
3. Remove the `phase/acceptance` label and apply `{{ target_phase }}`.
4. Post the transition marker:

```
PHASE-CHANGE: phase/acceptance -> {{ target_phase }} (reason: ACCEPTANCE-DECISION: Blocked — {{ reason }})
```

5. If the target is `phase/implementation`, reopen the closed sub-tasks that
   need changes, or open a new sub-task describing the required rework.

Sign your post with the persona header.
