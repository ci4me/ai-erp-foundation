---
id: consistency-check
description: Cross-state sweep that closes orphaned issues and PRs
---

## Action: Consistency Check Sweep

Persona: {{persona_name}} (`{{persona_id}}`)

This is a low-priority background sweep. It fixes three classes of drift:

1. PR merged but its linked issue is still open → close the issue with `ISSUE-CLOSED: DONE`.
2. Issue contains `ISSUE-CLOSED: DONE` but is still open → retry the close.
3. Issue has `REVIEW-VERDICT: APPROVE` but no open PR → close with comment "PR missing".

## Step-by-step execution

### Step 1: Collect open issues and merged PRs

```bash
gh issue list --repo "{{repo}}" --state open --limit 200 --json number,title,labels,body,comments,url > /tmp/open-issues.json
gh pr list --repo "{{repo}}" --state merged --limit 200 --json number,title,body,closingIssuesReferences > /tmp/merged-prs.json
gh pr list --repo "{{repo}}" --state open --limit 200 --json number,title,body,closingIssuesReferences > /tmp/open-prs.json
```

### Step 2: Run the sweep helper

```bash
python3 -m simulation.tools.next_prompt_consistency \
  --open-issues /tmp/open-issues.json \
  --merged-prs /tmp/merged-prs.json \
  --open-prs /tmp/open-prs.json \
  --report /tmp/consistency-report.json
```

### Step 3: Apply remediations (only in post_mode=real)

For each entry in the report:

- `class: merged_pr_open_issue` → `gh issue close <num> --reason completed --comment "ISSUE-CLOSED: DONE — PR #<pr> merged"`.
- `class: done_marker_still_open` → re-run `close_issue` action for that issue.
- `class: approve_no_pr` → comment `"PR missing"` and close with `ISSUE-CLOSED: REJECTED`.

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-consistency"
cat > "/tmp/consistency-summary.md" <<SUMMARY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Consistency sweep
Self-review conflict: No
Run-ID: ${RUN_ID}
---

CONSISTENCY-CHECK: FIXED count={{fixed_count}}

**Fixed:** {{fixed_count}}
**Skipped:** {{skipped_count}}
**Errors:** {{error_count}}
SUMMARY
```

### Step 4: Stop

Rerun `next_prompt.py` after the sweep so any newly closed issue does not re-enter a primary action.
