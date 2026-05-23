---
id: skip
description: Skip an iteration when the repo is intentionally saturated
---

## Action: Skip This Iteration

Reason: {{skip_reason}}

## Step-by-step execution

### Step 1: Post a short skip comment on Epic #1

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-loop-skip"
cat > "/tmp/loop-skip.md" <<SKIP
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (skip)
Self-review conflict: No
Run-ID: ${RUN_ID}
---

## End-of-run summary

**Iteration:** skip
**Reason:** {{skip_reason}}
**Open PRs:** {{open_pr_count}}

No new work was started because the open-PR limit is already saturated.
SKIP
gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/loop-skip.md"
````

### Step 2: Stop

Do not create a branch, PR, issue, or discussion in this iteration.
