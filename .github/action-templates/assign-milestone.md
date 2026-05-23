---
id: assign-milestone
description: Assign an issue to an existing milestone
---

## Action: Assign Issue #{{issue_number}} to Milestone

Persona: {{persona_name}} (`{{persona_id}}`)
Issue: #{{issue_number}} - {{issue_title}}
Requested milestone: {{requested_milestone_title}}

## Step-by-step execution

### Step 1: Verify the milestone exists

```bash
gh api "repos/{{repo}}/milestones?state=open&per_page=100" --jq '.[] | [.title,.number,.open_issues,.closed_issues] | @tsv'
```

STOP if `{{requested_milestone_title}}` does not exist. The next action should be `create_milestone`.

### Step 2: Assign the issue

```bash
if [ "{{post_mode}}" = "real" ]; then
  gh issue edit "{{issue_number}}" --repo "{{repo}}" --milestone "{{requested_milestone_title}}"
else
  echo "DRY-RUN: gh issue edit {{issue_number}} --repo {{repo}} --milestone \"{{requested_milestone_title}}\""
fi
```

### Step 3: Post audit comment

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-milestone-{{issue_number}}"
cat > "/tmp/issue-{{issue_number}}-milestone.md" <<COMMENT
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Issue #{{issue_number}} milestone assignment
Self-review conflict: No
Run-ID: ${RUN_ID}
---

MILESTONE-STATE: ASSIGNED issue#{{issue_number}} milestone="{{requested_milestone_title}}"
COMMENT
if [ "{{post_mode}}" = "real" ]; then
  gh issue comment "{{issue_number}}" --repo "{{repo}}" --body-file "/tmp/issue-{{issue_number}}-milestone.md"
else
  echo "DRY-RUN: gh issue comment {{issue_number}} --repo {{repo}} --body-file /tmp/issue-{{issue_number}}-milestone.md"
fi
```
