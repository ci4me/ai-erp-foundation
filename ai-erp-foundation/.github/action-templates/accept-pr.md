---
id: accept-pr
description: Record an explicit ACCEPT / HOLD / REJECT decision before merge
---

## Action: Accept / Hold / Reject PR #{{pr_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

This is the final acceptance decision before merge. It does **not** merge the PR. It writes the machine-readable marker that lets the next `next_prompt.py` run choose `merge_pr` or `reject_pr`.

## Current PR

- PR: #{{pr_number}} - {{pr_title}}
- URL: {{pr_url}}
- Required reviewers: {{required_reviewers}}
- Posted reviewers: {{posted_reviewers}}
- Outstanding reviewers: {{outstanding_reviewers}}

## Policy check

{{policy_check}}

## Step-by-step execution

### Step 1: Re-read PR state

```bash
gh pr view "{{pr_number}}" --repo "{{repo}}" --json number,title,mergeable,reviewDecision,statusCheckRollup,comments,reviews,files,url
```

STOP unless all required reviews are present, no blocking `REQUEST_CHANGES` remains, and CI is not red.

### Step 2: Choose exactly one decision

Allowed decisions:

- `ACCEPT` - all gates pass and the PR may move to `merge_pr`.
- `HOLD` - not ready, but not permanently rejected.
- `REJECT` - close the PR without merge because the scope is invalid, superseded, unsafe, or abandoned.

### Step 3: Write the decision body

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-accept-pr{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-acceptance.md" <<DECISION
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: PR #{{pr_number}} acceptance gate
Self-review conflict: {{self_review_conflict}}
Run-ID: ${RUN_ID}
---

ACCEPTANCE-DECISION: ACCEPT|HOLD|REJECT PR#{{pr_number}} -- CHANGE_ME_REASON

**Decision:** ACCEPT | HOLD | REJECT

**Gate evidence:**
| Gate | Status | Evidence |
| --- | --- | --- |
| Required reviews | PASS/FAIL | CHANGE_ME |
| CI/checks | PASS/FAIL | CHANGE_ME |
| Policy labels | PASS/FAIL | CHANGE_ME |
| Human sign-off, if required | PASS/FAIL/NA | CHANGE_ME |

**Reason:** CHANGE_ME

**Next action:** If ACCEPT, rerun `next_prompt.py` and it should select `merge_pr`. If REJECT, rerun and it should select `reject_pr`. If HOLD, fix the listed blocker first.
DECISION
```

### Step 4: Validate no unresolved placeholders

```bash
python - <<'PY'
from pathlib import Path
text = Path('/tmp/pr-{{pr_number}}-acceptance.md').read_text()
for bad in ['ACCEPT|HOLD|REJECT', 'ACCEPT | HOLD | REJECT', 'CHANGE_ME']:
    if bad in text:
        raise SystemExit(f'Unresolved acceptance placeholder: {bad}')
if 'ACCEPTANCE-DECISION:' not in text:
    raise SystemExit('Missing ACCEPTANCE-DECISION marker')
print('acceptance body validation passed')
PY
python -m simulation.tools.validate_agent_action --kind acceptance-decision --persona "{{persona_id}}" --file "/tmp/pr-{{pr_number}}-acceptance.md"
```

### Step 5: Post the decision

```bash
if [ "{{post_mode}}" = "real" ]; then
  gh pr comment "{{pr_number}}" --repo "{{repo}}" --body-file "/tmp/pr-{{pr_number}}-acceptance.md"
else
  echo "DRY-RUN: gh pr comment {{pr_number}} --repo {{repo}} --body-file /tmp/pr-{{pr_number}}-acceptance.md"
fi
```

### Step 6: Stop

Do not merge or close in this same iteration. Rerun `next_prompt.py`; the changed GitHub state decides the next action.
