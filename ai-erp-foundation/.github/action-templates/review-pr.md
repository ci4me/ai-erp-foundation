---
id: review-pr
description: Review an open pull request from the selected persona's lens
---

## Action: Review PR #{{pr_number}} as {{persona_name}}

You are the persona selected by live GitHub state:

- Persona id: `{{persona_id}}`
- Persona name: {{persona_name}}
- Role: {{persona_role}}
- Layer: {{persona_layer}}
- Lens: {{persona_lens}}
- Model default: {{persona_model_default}}
- Persona prompt source: `{{persona_prompt_path}}`
- Allowed verdicts: {{persona_verdict_enum}}
- Self-review conflict for this PR: {{self_review_conflict}}

### Other legal actions for {{persona_name}}

{{persona_action_menu}}

### Why this PR was selected

- PR: #{{pr_number}} - {{pr_title}}
- URL: {{pr_url}}
- Author: @{{pr_author}}
- Branch: `{{pr_head_ref}}` -> `{{pr_base_ref}}`
- Labels: {{pr_labels}}
- Required reviewers from PR body or persona activation: {{required_reviewers}}
- Reviewers already found in comments/reviews: {{posted_reviewers}}
- Reviewers still outstanding: {{outstanding_reviewers}}
- Next reviewer after you, if any: {{next_reviewer_persona}}

### Policy-derived requirements

{{policy_check}}

### Existing review history from GitHub

{{review_history}}

### Files changed

{{pr_changed_files}}

### Universal preamble, if this persona inherits it

{{inherits_preamble}}

### PR diff snapshot

Read this before the PR body.

{{pr_diff_note}}

````diff
{{pr_diff}}
````

### Linked issue context

```markdown
{{linked_issue_context}}
```

### Persona-specific context pack

```markdown
{{persona_context_pack}}
```

### Full persona prompt to obey

```markdown
{{persona_prompt}}
```

### PR body from GitHub

Read only after you have built your own claim list from the diff.

```markdown
{{pr_body}}
```

## Step-by-step execution

### Step 1: Set shell variables

Run:

````bash
export REPO="{{repo}}"
export PR_NUMBER="{{pr_number}}"
export PERSONA_ID="{{persona_id}}"
export POST_MODE="{{post_mode}}"
# Set after writing the review body: approve | request-changes | comment
export REVIEW_MODE="comment"
````

### Step 2: Refresh the exact PR state locally

Run:

````bash
gh pr diff "$PR_NUMBER" --repo "$REPO" > "/tmp/pr-${PR_NUMBER}.diff"
gh pr view "$PR_NUMBER" --repo "$REPO" --json number,title,labels,author,headRefName,baseRefName,comments,reviews,files,url > "/tmp/pr-${PR_NUMBER}-meta.json"
````

Read `/tmp/pr-${PR_NUMBER}.diff` before trusting the PR body. Build your own claim list from the diff, then compare it to the PR body.

### Step 3: Apply the persona lens

Use the persona prompt above as the source of truth. Specifically:

- Use only verdicts from: {{persona_verdict_enum}}
- Do not claim evidence without a `path:line` or a diff hunk reference.
- If the PR body claims something not present in the diff, mark it `NOT_FOUND_IN_DIFF`.
- If `Self-review conflict` is `Yes`, explicitly say the review may be biased by the operating model that produced it.

## DO NOTs for this action

- Do NOT trust the PR body before reading the diff. The diff is the source of truth.
- Do NOT post a review without the signed YAML persona header.
- Do NOT use a verdict outside the selected persona's `verdict_enum`.
- Do NOT approve when required evidence is missing; use `APPROVE_WITH_CONDITIONS`, `COMMENT`, `ABSTAIN`, `REQUEST_CHANGES`, or `BLOCK` as allowed by the persona.
- Do NOT select or ping the next reviewer manually. The next reviewer comes from rerunning `next_prompt.py`.
- Do NOT post duplicate reviews for a persona already listed in review history unless the prompt explicitly selected that persona after new changes.

### Step 4: Create the PR review comment

Choose one verdict from the allowed set, then write the final review into the template below. Replace every placeholder before posting.

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-pr{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-{{persona_id}}-review.md" <<REVIEW
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: PR #{{pr_number}} diff + PR body + changed files: {{pr_changed_files_inline}}
Self-review conflict: {{self_review_conflict}}
Run-ID: ${RUN_ID}
---

{{persona_comment_template}}
REVIEW
````

Open `/tmp/pr-{{pr_number}}-{{persona_id}}-review.md` and replace placeholder text with your actual review.

### Step 5: Validate the review body

Run:

````bash
python - <<'PY'
from pathlib import Path
path = Path("/tmp/pr-{{pr_number}}-{{persona_id}}-review.md")
text = path.read_text()
for bad in ["CHANGE_ME", "APPROVE |", "REQUEST_CHANGES |", "[", "]", "1. ...", "(2-3 sentences)", "(one specific question", "PASTE", "COPY YOUR"]:
    if bad in text:
        raise SystemExit(f"Unresolved placeholder/token in review body: {bad}")
if "Persona: {{persona_id}}" not in text:
    raise SystemExit("Missing persona header")
if "Run-ID:" not in text:
    raise SystemExit("Missing Run-ID")
required = ["**Verdict:**", "**Acceptance matrix:**", "**Blocking findings:**", "**Non-blocking findings:**", "**Required next action:**"]
for heading in required:
    if heading not in text:
        raise SystemExit(f"Missing required review section: {heading}")
print("review body validation passed")
PY
python -m simulation.tools.validate_agent_action --kind pr-review --persona "{{persona_id}}" --file "/tmp/pr-{{pr_number}}-{{persona_id}}-review.md"
````

### Step 6: Post the PR review

Map your verdict to the GitHub review action:

- `APPROVE` -> `--approve`
- `REQUEST_CHANGES` or `BLOCK` -> `--request-changes`
- `APPROVE_WITH_CONDITIONS`, `COMMENT`, `ABSTAIN`, or any other non-blocking/commentary verdict -> `--comment`

Set `REVIEW_MODE` based on your verdict, then run this single guarded command:

````bash
case "$REVIEW_MODE" in
  approve) REVIEW_FLAG="--approve" ;;
  request-changes) REVIEW_FLAG="--request-changes" ;;
  comment) REVIEW_FLAG="--comment" ;;
  *) echo "REVIEW_MODE must be approve, request-changes, or comment"; exit 1 ;;
esac

if [ "$POST_MODE" = "real" ]; then
  gh pr review "{{pr_number}}" --repo "{{repo}}" "$REVIEW_FLAG" --body-file "/tmp/pr-{{pr_number}}-{{persona_id}}-review.md"
else
  echo "DRY-RUN: gh pr review {{pr_number}} --repo {{repo}} $REVIEW_FLAG --body-file /tmp/pr-{{pr_number}}-{{persona_id}}-review.md"
fi
````

### Step 7: Post the end-of-run summary to Epic #1

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-summary-pr{{pr_number}}"
: "${REVIEW_VERDICT:?Set REVIEW_VERDICT to the verdict you posted}"
: "${COST_ESTIMATE:=<$0.25; no paid model API invoked}"
cat > "/tmp/pr-{{pr_number}}-{{persona_id}}-summary.md" <<SUMMARY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (review_pr)
Self-review conflict: {{self_review_conflict}}
Run-ID: ${RUN_ID}
---

## End-of-run summary

**Iteration:** review_pr
**PR reviewed:** #{{pr_number}} - {{pr_title}}
**Persona:** {{persona_name}} (`{{persona_id}}`)
**Verdict posted:** ${REVIEW_VERDICT}

**Reviewers before this run:** {{posted_reviewers}}
**Outstanding reviewers before this run:** {{outstanding_reviewers}}
**Next expected loop action:** rerun `next_prompt.py`; it should re-read GitHub comments and select the next outstanding reviewer or blocker.

**Cost this iteration:** ${COST_ESTIMATE}
SUMMARY
python - <<'PY'
from pathlib import Path
path = Path("/tmp/pr-{{pr_number}}-{{persona_id}}-summary.md")
text = path.read_text()
for bad in ["[", "]", "PASTE", "COPY YOUR"]:
    if bad in text:
        raise SystemExit(f"Unresolved placeholder/token in summary body: {bad}")
print("summary body validation passed")
PY
if [ "$POST_MODE" = "real" ]; then
  gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/pr-{{pr_number}}-{{persona_id}}-summary.md"
else
  echo "DRY-RUN: gh issue comment 1 --repo {{repo}} --body-file /tmp/pr-{{pr_number}}-{{persona_id}}-summary.md"
fi
````

### Step 8: Stop

Do not select the next reviewer yourself. The next session must run `next_prompt.py` again against GitHub state after your comments exist.
