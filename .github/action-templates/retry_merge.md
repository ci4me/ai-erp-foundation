---
id: retry-merge
description: Retry a failed merge attempt within the retry budget
---

## Action: Retry Merge for PR #{{pr_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Previous attempts: {{merge_loop_count}} / {{max_retries}}
Last failure: {{last_failure_reason}}

## Step-by-step execution

### Step 1: Confirm PR is still mergeable

```bash
gh pr view "{{pr_number}}" --repo "{{repo}}" --json number,state,mergeable,mergeStateStatus,headRefName
```

If the PR is closed/missing, transition to `close_issue` with reason "PR not found".

If `merge_loop_count >= max_retries`, STOP and emit:

```text
RETRY-MERGE: EXHAUSTED PR#{{pr_number}}
```

then route to `address_changes_requested` or close depending on the underlying failure.

### Step 2: Re-check release gate

The retry only proceeds if `RHEA-VERDICT: MERGE_READY` and `ACCEPTANCE-DECISION: ACCEPT` markers are present on the PR.

### Step 3: Attempt merge once

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-retry-merge-{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-retry-merge.md" <<RETRY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: PR #{{pr_number}} merge retry {{merge_loop_count}}/{{max_retries}}
Self-review conflict: No
Run-ID: ${RUN_ID}
---

RETRY-MERGE: QUEUED PR#{{pr_number}} attempt={{merge_loop_count}}/{{max_retries}}

**Last failure:** {{last_failure_reason}}
**Why retry is safe:** CHANGE_ME
RETRY

if [ "{{post_mode}}" = "real" ]; then
  gh pr merge "{{pr_number}}" --repo "{{repo}}" --merge --delete-branch || \
    echo "MERGE-STATUS: FAILED PR#{{pr_number}}" | tee -a "/tmp/pr-{{pr_number}}-retry-merge.md"
else
  echo "DRY-RUN: gh pr merge {{pr_number}} --repo {{repo}} --merge"
fi
```

### Step 4: Post outcome

On success the merge action posts `MERGE-STATUS: COMPLETE`. On failure post the retry marker above so the scheduler can re-enter this action.
