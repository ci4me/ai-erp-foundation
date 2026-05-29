# Action: create_sub_issues

You are {{ persona }}. A `DECOMPOSITION-PLAN:` has been posted on parent epic
#{{ parent_issue }}. Create one GitHub issue per `SUB-TASK:` line.

For each sub-issue:
- Title: the SUB-TASK title.
- Body: include `Parent epic: #{{ parent_issue }}` and, if the SUB-TASK has a
  real `depends-on: #<issue>`, add a line `Depends on: #<issue>`.
- Label: `sub-task`.
- Assignee: the suggested `@persona` if it is a valid persona.

Idempotency (required):
- Before creating, check for existing children — any issue whose body already
  contains `Parent epic: #{{ parent_issue }}`. Do **not** recreate those.

After creating the issues, edit the `DECOMPOSITION-PLAN:` comment to replace each
`SUB-TASK:` title with a link to its real issue number.

Sign your post with the persona header.
