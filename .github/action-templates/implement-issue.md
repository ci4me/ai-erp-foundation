---
id: implement-issue
description: Implement a ready issue and open a PR
---

## Action: Implement Issue #{{issue_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

```markdown
{{issue_body}}
```

## Steps

1. Create a branch named from the issue.
2. Implement only the issue acceptance criteria.
3. Run the narrowest relevant verification.
4. Open a PR whose required reviewers are derived from persona `actions.primary/support` plus labels.

```bash
git checkout -b "issue-{{issue_number}}-[short-slug]"
# edit files
git status --short
# run focused tests/checks
git add [changed files]
git commit -m "feat: implement issue {{issue_number}}

Closes #{{issue_number}}.

Co-Authored-By: [YOUR MODEL NAME] <noreply@example.com>"
git push -u origin "issue-{{issue_number}}-[short-slug]"
```

Open the PR with `risk:*` labels required by policy, never weaker than `risk:high` if operating-model paths are touched.

## Optional Chaining

When the implementation is small and the next step is mechanical, end the
output with a chain marker so the loop runs the next action without a
fresh GitHub fetch:

```
CHAIN-NEXT: review_pr
```

Allowed next actions in the chain: `review_pr`, `merge_pr`, `close_issue`,
`request_clarification`. Do **not** chain `triage_issue` or
`design_solution` — those need a fresh state read.
