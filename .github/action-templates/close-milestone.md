---
id: close-milestone
description: Close a milestone after all issues are closed
---

## Action: Close Milestone #{{milestone_number}} `{{milestone_title}}`

Persona: {{persona_name}} (`{{persona_id}}`)
Open issues: {{milestone_open_issues}}
Closed issues: {{milestone_closed_issues}}
Due: {{milestone_due_on}}

## Step-by-step execution

### Step 1: Re-verify milestone is complete

```bash
gh api "repos/{{repo}}/milestones/{{milestone_number}}" --jq '{number,title,state,open_issues,closed_issues,due_on}'
```

STOP unless `open_issues` is `0` and `closed_issues` is greater than `0`.

### Step 2: Close milestone

```bash
if [ "{{post_mode}}" = "real" ]; then
  gh api "repos/{{repo}}/milestones/{{milestone_number}}" --method PATCH -f state=closed
else
  echo "DRY-RUN: gh api repos/{{repo}}/milestones/{{milestone_number}} --method PATCH -f state=closed"
fi
```

### Step 3: Post Epic summary

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-close-milestone{{milestone_number}}"
cat > "/tmp/milestone-{{milestone_number}}-closed.md" <<SUMMARY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Milestone #{{milestone_number}} closure
Self-review conflict: No
Run-ID: ${RUN_ID}
---

MILESTONE-STATE: CLOSED milestone#{{milestone_number}}

**Milestone:** {{milestone_title}}
**Closed issues:** {{milestone_closed_issues}}
**Open issues at close:** {{milestone_open_issues}}
SUMMARY
if [ "{{post_mode}}" = "real" ]; then
  gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/milestone-{{milestone_number}}-closed.md"
else
  echo "DRY-RUN: gh issue comment 1 --repo {{repo}} --body-file /tmp/milestone-{{milestone_number}}-closed.md"
fi
```
