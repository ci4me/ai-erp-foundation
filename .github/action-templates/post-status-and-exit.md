---
id: post-status-and-exit
description: Report that the loop found no available work
---

## Action: Post Status and Exit

Reason: {{status_reason}}

## Step-by-step execution

### Step 1: Confirm state

Run:

````bash
python -m simulation.tools.next_prompt --repo "{{repo}}" --probe-only
````

### Step 2: Post a status comment on Epic #1

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-loop-status"
cat > "/tmp/loop-status.md" <<STATUS
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (post_status_and_exit)
Self-review conflict: No
Run-ID: ${RUN_ID}
---

## End-of-run summary

**Iteration:** post_status_and_exit
**Open PRs:** {{open_pr_count}}
**Open issues:** {{open_issue_count}}
**Missing personas:** {{missing_personas}}
**Missing scenarios:** {{scenarios_without_scorecards}}

No available autonomous-loop work was selected.
STATUS
gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/loop-status.md"
````

### Step 3: Stop

Do not open new work unless a future `next_prompt.py` run selects it.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
LOOP-STATUS: NO_WORK
```

Allowed values: `NO_WORK`, `BLOCKED`.
