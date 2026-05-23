---
id: close-issue
description: Close an issue after explicit accepted/rejected/done state
---

## TL;DR

Close this issue by commenting `ISSUE-CLOSED: {{issue_close_reason}}` with a
one-line summary. Do not add any other text.

## Action: Close Issue #{{issue_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Issue title: {{issue_title}}
Labels: {{issue_labels}}
Close reason: {{issue_close_reason}}

## Step-by-step execution

### Step 1: Verify terminal state

```bash
gh issue view "{{issue_number}}" --repo "{{repo}}" --json number,title,state,body,labels,comments,url
```

STOP unless the issue has a terminal marker or label: `ready-to-close`, `agent:close`, `state:accepted`, `resolution:accepted`, `resolution:rejected`, or `ISSUE-STATE: READY_TO_CLOSE`.

### Step 2: Prepare closing comment

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-close-issue{{issue_number}}"
cat > "/tmp/issue-{{issue_number}}-close.md" <<CLOSE
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Issue #{{issue_number}} close gate
Self-review conflict: No
Run-ID: ${RUN_ID}
---

ISSUE-STATE: CLOSED issue#{{issue_number}} reason={{issue_close_reason}}

**Evidence:**
- CHANGE_ME

**Follow-up:** CHANGE_ME or `none`
CLOSE
python - <<'PY'
from pathlib import Path
text = Path('/tmp/issue-{{issue_number}}-close.md').read_text()
if 'CHANGE_ME' in text:
    raise SystemExit('Unresolved close issue placeholder')
print('close issue body validation passed')
PY
```

### Step 3: Close the issue

```bash
if [ "{{post_mode}}" = "real" ]; then
  gh issue close "{{issue_number}}" --repo "{{repo}}" --reason "{{issue_close_reason}}" --comment "$(cat /tmp/issue-{{issue_number}}-close.md)"
else
  echo "DRY-RUN: gh issue close {{issue_number}} --repo {{repo}} --reason {{issue_close_reason}} --comment \"$(cat /tmp/issue-{{issue_number}}-close.md)\""
fi
```

### Step 4: Stop

Do not close any related milestones in this iteration. Rerun `next_prompt.py`.
