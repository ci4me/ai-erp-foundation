---
id: address-changes-requested
description: Address the oldest open PR with CHANGES_REQUESTED or a blocking review
---

## Action: Address CHANGES_REQUESTED on PR #{{pr_number}}

You are acting as:

- Persona id: `{{persona_id}}`
- Persona name: {{persona_name}}
- Role: {{persona_role}}
- Model default: {{persona_model_default}}

### PR blocker selected from GitHub

- PR: #{{pr_number}} - {{pr_title}}
- URL: {{pr_url}}
- Blocker author: @{{blocker_author}}
- Blocker timestamp: {{blocker_created_at}}
- Blocker URL: {{blocker_url}}

Blocker body:

```markdown
{{blocker_body}}
```

## Step-by-step execution

### Step 1: Checkout the PR

Run:

````bash
gh pr checkout "{{pr_number}}" --repo "{{repo}}"
````

### Step 2: Inspect the blocker and current diff

Run:

````bash
gh pr view "{{pr_number}}" --repo "{{repo}}" --json number,title,body,comments,reviews,files > "/tmp/pr-{{pr_number}}-blocker-state.json"
gh pr diff "{{pr_number}}" --repo "{{repo}}" > "/tmp/pr-{{pr_number}}-before-fix.diff"
````

Read the blocker body above and fix only the smallest concrete issue that satisfies it.

### Step 3: Make the minimal code/doc/template change

Rules:

- Do not refactor unrelated code.
- Do not address unrelated comments in the same commit.
- Do not edit persona prompts unless the blocker explicitly requires it and the current branch is meant to carry that operating-model change.
- Keep the change reviewable.

### Step 4: Verify locally

Run the narrowest relevant command. Prefer one of:

````bash
python -m pytest simulation/tests
python -m simulation.tools.next_prompt --repo "{{repo}}" --probe-only
python simulation/run.py --mode dry-run
````

### Step 5: Commit and push

Run:

````bash
git status --short
git add [ONLY_THE_FILES_YOU_CHANGED]
git commit -m "fix(loop): address PR {{pr_number}} blocker

Addresses @{{blocker_author}}'s blocking review on PR #{{pr_number}}.

Co-Authored-By: [YOUR MODEL NAME] <noreply@example.com>"
git push
````

### Step 6: Reply on the PR

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-{{persona_id}}-blocker-pr{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-blocker-reply.md" <<REPLY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (address_changes_requested)
Self-review conflict: No
Run-ID: ${RUN_ID}
---

## Blocker addressed

@{{blocker_author}}, I pushed a focused fix for the blocking review on PR #{{pr_number}}.

**Commit:** [PASTE `git log --oneline -1`]
**What changed:** [ONE SENTENCE]
**Verification:** [COMMAND + RESULT]

Ready for re-review.
REPLY
gh pr comment "{{pr_number}}" --repo "{{repo}}" --body-file "/tmp/pr-{{pr_number}}-blocker-reply.md"
````

### Step 7: Post the end-of-run summary to Epic #1

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-{{persona_id}}-summary-pr{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-blocker-summary.md" <<SUMMARY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (address_changes_requested)
Self-review conflict: No
Run-ID: ${RUN_ID}
---

## End-of-run summary

**Iteration:** address_changes_requested
**PR:** #{{pr_number}} - {{pr_title}}
**Blocker author:** @{{blocker_author}}
**Commit pushed:** [YES/NO + SHA]
**Verification:** [COMMAND + RESULT]

**Next expected loop action:** rerun `next_prompt.py`; it will re-check the PR review state.
SUMMARY
gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/pr-{{pr_number}}-blocker-summary.md"
````


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
ADDRESS-CHANGES: POSTED
```

Allowed values: `POSTED`, `BLOCKED`.
