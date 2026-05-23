---
id: create-issue
description: Open a new issue from a discussion, review, audit, or explicit create marker
---

## Action: Create Issue from {{source_kind}} #{{source_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Source title: {{source_title}}
Source URL: {{source_url}}

## Step-by-step execution

### Step 1: Re-read the source

```bash
# If source is an issue:
gh issue view "{{source_number}}" --repo "{{repo}}" --json number,title,body,labels,url || true
```

For a Discussion source, use the URL above and the embedded body below.

### Step 2: Draft exactly one bounded issue

```bash
cat > "/tmp/create-issue-body.md" <<ISSUE
AGENT-SOURCE: {{source_kind}}#{{source_number}}

## User / system outcome
CHANGE_ME

## Acceptance criteria
- [ ] CHANGE_ME

## Out of scope
- CHANGE_ME

## Owner persona
CHANGE_ME_PERSONA_ID

## Required reviewers
- CHANGE_ME_PERSONA_ID

## Source evidence
- {{source_url}}
ISSUE
python - <<'PY'
from pathlib import Path
text = Path('/tmp/create-issue-body.md').read_text()
for bad in ['CHANGE_ME']:
    if bad in text:
        raise SystemExit(f'Unresolved issue placeholder: {bad}')
print('new issue body validation passed')
PY
```

### Step 3: Create the issue

```bash
ISSUE_TITLE="{{proposed_issue_title}}"
if [ "{{post_mode}}" = "real" ]; then
  gh issue create --repo "{{repo}}" --title "$ISSUE_TITLE" --body-file "/tmp/create-issue-body.md" --label "needs-triage"
else
  echo "DRY-RUN: gh issue create --repo {{repo}} --title \"$ISSUE_TITLE\" --body-file /tmp/create-issue-body.md --label needs-triage"
fi
```

### Step 4: Stop

The new issue must be triaged by a future `next_prompt.py` run.
