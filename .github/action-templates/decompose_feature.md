# Action: decompose_feature

You are {{ persona }}. Issue #{{ parent_issue }} is labelled `epic` and is too
large for a single PR. Using the design resolution and discussion history,
produce a decomposition plan that breaks the work into concrete, independent
sub-tasks — each small enough to ship in one PR.

Post a comment in exactly this format:

```
DECOMPOSITION-PLAN:
SUB-TASK: <title> (effort: <S/M/L/XL>, depends-on: #<issue>, assignee: @<persona>)
SUB-TASK: <title> (effort: <S/M/L/XL>, depends-on: #<issue>, assignee: @<persona>)
```

Guidelines:
- List sub-tasks in execution order (dependencies first).
- Use `depends-on: #<issue>` only when the sub-task truly cannot start before
  another sub-issue completes; otherwise use `depends-on: none`.
- `assignee` is a suggestion — the planner uses dynamic persona discovery to
  assign the work.
- A valid plan has at least two `SUB-TASK:` lines.

Sign your post with the persona header.
