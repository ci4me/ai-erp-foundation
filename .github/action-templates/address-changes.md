---
id: address-changes-requested
title: Address CHANGES_REQUESTED
description: Fix the oldest PR that has REQUEST_CHANGES
required_variables:
  - repo
  - pr_number
  - pr_title
  - oldest_blocker_comment
  - oldest_blocker_author
  - persona_id
  - persona_name
  - persona_role
  - persona_model_default
---

# Fix PR #{{pr_number}} — CHANGES_REQUESTED blocker

Your task: Address the most recent `REQUEST_CHANGES` comment on this PR and push a fix.

## Current state

| Item | Value |
| --- | --- |
| PR | #{{pr_number}} — {{pr_title}} |
| Blocker by | @{{oldest_blocker_author}} |
| Repo | {{repo}} |

## The blocker comment

```
{{oldest_blocker_comment}}
```

## Step-by-step execution

### Step 1: Understand the blocker

Re-read the comment above. Identify ONE concrete issue to fix (do not try to fix all at once in one commit).

### Step 2: Checkout the PR branch

Run:
```bash
gh pr checkout {{pr_number}} -R {{repo}}
```

### Step 3: Apply the fix

Make the minimal change that addresses the blocker.

Do NOT:
- Refactor unrelated code
- Fix other issues in the same PR
- Add new features

Just fix this one blocker.

### Step 4: Commit with a clear message

Run:
```bash
git commit -m "fix(scope): [blocker summary]

Addresses @{{oldest_blocker_author}}'s REQUEST_CHANGES on PR #{{pr_number}}.

- [What you changed]
- [Why it fixes the blocker]"
```

### Step 5: Push the commit

Run:
```bash
git push
```

### Step 6: Reply to the blocker comment

Run:
```bash
gh pr comment {{pr_number}} -R {{repo}} --body "$(cat <<'REPLY'
---
Persona: {{persona_id}}
Role: {{persona_role}}
Model: {{persona_model_default}}
Source: autonomous-loop (address_changes_requested)
Self-review conflict: No
Run-ID: $(date -u +%Y-%m-%dT%H:%M:%SZ)-{{persona_id}}-blocker
---

## Blocker addressed

@{{oldest_blocker_author}}, I've pushed a fix for your REQUEST_CHANGES comment:

- **Commit:** [git log --oneline -1]
- **What changed:** [summary of your fix]
- **Why:** [explanation]

The blocker should now be resolved. Ready for your re-review when you are.
REPLY
)"
```

### Step 7: Post end-of-run summary

Run:
```bash
gh issue comment 1 -R {{repo}} --body "$(cat <<'SUMMARY'
---
Persona: auto-loop
Role: Autonomous Loop Dispatcher
Model: n/a
Source: autonomous-loop iteration (address_changes_requested)
Self-review conflict: No
Run-ID: $(date -u +%Y-%m-%dT%H:%M:%SZ)-loop
---

## End-of-run summary

**Iteration:** address_changes_requested
**PR:** #{{pr_number}} — {{pr_title}}
**Blocker fixed:** ✓
**Reply posted:** ✓

**Next iteration will:** Re-evaluate PR #{{pr_number}} for additional blockers or promotion to next reviewer.
SUMMARY
)"
```

## Hard caps (NON-NEGOTIABLE)

- Max 3 file Writes per iteration
- Max 2 sub-agent dispatches
- Max 6 Bash calls
- Per-iteration budget ceiling: $5.00
- Never bypass commit hooks (`--no-verify`)
- Never force-push
- Sign all comments with v0.3 YAML header
- End with `Co-Authored-By:` trailer in commit
- Post end-of-run summary on Epic #1
