---
id: retry-implementation
description: Retry a failed implementation attempt within the retry budget
---

## Action: Retry Implementation for Issue #{{issue_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Previous attempts: {{implement_loop_count}} / {{max_retries}}
Last failure: {{last_failure_reason}}

## Step-by-step execution

### Step 1: Confirm retry budget is not exhausted

If `implement_loop_count >= max_retries`, STOP and emit:

```text
RETRY-IMPLEMENTATION: EXHAUSTED issue#{{issue_number}}
```

then transition to `close_issue` with `ISSUE-CLOSED: UNRESOLVED` and add label `stuck`.

### Step 2: Inspect the previous failure

```bash
gh issue view "{{issue_number}}" --repo "{{repo}}" --json number,title,body,labels,comments
gh pr list --repo "{{repo}}" --state all --search "in:body #{{issue_number}}" --json number,state,headRefName
```

Identify whether the failure was: build, test, lint, type-check, or merge conflict.

### Step 3: Re-implement with the narrowest possible change

Check out a fresh branch from `main`, apply only the smallest change needed to address the prior failure, run the matching local validation, and push.

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-retry-impl-{{issue_number}}"
cat > "/tmp/issue-{{issue_number}}-retry.md" <<RETRY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Issue #{{issue_number}} retry attempt {{implement_loop_count}}/{{max_retries}}
Self-review conflict: No
Run-ID: ${RUN_ID}
---

RETRY-IMPLEMENTATION: QUEUED issue#{{issue_number}} attempt={{implement_loop_count}}/{{max_retries}}

**Last failure:** {{last_failure_reason}}
**Narrow fix:** CHANGE_ME
**Verification:** CHANGE_ME
RETRY
```

### Step 4: Post and stop

```bash
if [ "{{post_mode}}" = "real" ]; then
  gh issue comment "{{issue_number}}" --repo "{{repo}}" --body-file "/tmp/issue-{{issue_number}}-retry.md"
else
  echo "DRY-RUN: gh issue comment {{issue_number}} --repo {{repo}} --body-file /tmp/issue-{{issue_number}}-retry.md"
fi
```

Rerun `next_prompt.py` after the retry PR is open.
