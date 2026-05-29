---
id: create-milestone
description: Create a GitHub milestone from an explicit milestone request
---

## Action: Create Milestone `{{requested_milestone_title}}`

Persona: {{persona_name}} (`{{persona_id}}`)
Source issue: #{{source_issue_number}} - {{source_issue_title}}

## Step-by-step execution

### Step 1: Check existing milestones

```bash
gh api "repos/{{repo}}/milestones?state=all&per_page=100" --jq '.[] | [.number,.title,.state,.open_issues,.closed_issues] | @tsv'
```

STOP if a milestone with the same title already exists. Use `assign_milestone` instead.

### Step 2: Create milestone

```bash
cat > "/tmp/milestone-create.json" <<JSON
{
  "title": "{{requested_milestone_title}}",
  "description": "Created by autonomous loop from issue #{{source_issue_number}}. Fill in scope and due_on after triage.",
  "state": "open"
}
JSON
if [ "{{post_mode}}" = "real" ]; then
  gh api "repos/{{repo}}/milestones" --method POST --input "/tmp/milestone-create.json"
else
  echo "DRY-RUN: gh api repos/{{repo}}/milestones --method POST --input /tmp/milestone-create.json"
fi
```

### Step 3: Stop

Rerun `next_prompt.py`; it may assign issues to the milestone next.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
MILESTONE-STATE: CREATED
```

Allowed values: `CREATED`, `ASSIGNED`, `CLOSED`.
