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
