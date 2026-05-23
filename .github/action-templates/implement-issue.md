---
id: implement-issue
description: Implement a ready issue and open a PR
---

## CRITICAL — STRICT CODE RULE (READ FIRST)

This action exists to **ship real code**. Note-only and markdown-only
PRs are rejected by `simulation.tools.validator.validate_pr_has_code`
and the loop will refuse to merge them.

- **Do NOT** open a PR that only changes `.md`, `.txt`, `.yml`,
  `.json`, `.yaml` files unless the issue explicitly says "docs-only".
- **Do NOT** open a PR whose only diff is a comment-only file like
  `notes.md`, `TODO.md`, `implement-note.md`.
- **Every PR must include at least one source file** with extension:
  `.php`, `.js`, `.ts`, `.jsx`, `.tsx`, `.py`, `.go`, `.java`, `.rb`,
  `.c`, `.cpp`, `.rs`, `.sql`. Add tests in the same language when the
  project has a test suite.
- **PR body must contain** `IMPLEMENTATION-COMPLETE: READY_FOR_REVIEW`
  and a `Files changed:` list with paths.

Example of a valid PR description:

```
IMPLEMENTATION-COMPLETE: READY_FOR_REVIEW

Files changed:
- src/Auth/User.php
- tests/Auth/UserTest.php

This PR implements JWT-based user authentication.
```

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
