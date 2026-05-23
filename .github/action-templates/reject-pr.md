---
id: reject-pr
description: Close a PR after an explicit REJECT decision
---

## Action: Reject / Close PR #{{pr_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Only run this after the PR contains an explicit terminal marker such as `ACCEPTANCE-DECISION: REJECT`, `PR-STATE: REJECTED`, or `RHEA-VERDICT: REJECT`.

## Step-by-step execution

### Step 1: Verify the rejection marker

```bash
gh pr view "{{pr_number}}" --repo "{{repo}}" --json number,title,state,comments,reviews,url
```

STOP unless a latest relevant comment/review contains an explicit reject marker.

### Step 2: Prepare the closing comment

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-reject-pr{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-reject.md" <<REJECT
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: PR #{{pr_number}} rejection closure
Self-review conflict: {{self_review_conflict}}
Run-ID: ${RUN_ID}
---

PR-STATE: REJECTED PR#{{pr_number}}

**Reason:** CHANGE_ME

**Evidence:**
- CHANGE_ME

**Follow-up, if any:** CHANGE_ME or `none`
REJECT
python - <<'PY'
from pathlib import Path
text = Path('/tmp/pr-{{pr_number}}-reject.md').read_text()
for bad in ['CHANGE_ME']:
    if bad in text:
        raise SystemExit(f'Unresolved rejection placeholder: {bad}')
print('reject body validation passed')
PY
```

### Step 3: Close the PR

```bash
if [ "{{post_mode}}" = "real" ]; then
  gh pr close "{{pr_number}}" --repo "{{repo}}" --comment "$(cat /tmp/pr-{{pr_number}}-reject.md)"
else
  echo "DRY-RUN: gh pr close {{pr_number}} --repo {{repo}} --comment \"$(cat /tmp/pr-{{pr_number}}-reject.md)\""
fi
```

### Step 4: Stop

Do not open replacement work unless a future `next_prompt.py` run selects `create_issue` or `open_followup_issue`.
