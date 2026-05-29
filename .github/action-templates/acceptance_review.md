# Action: acceptance_review

You are {{ persona }}. Epic #{{ issue_number }} has passed all tests
(`TEST-REPORT: Pass`) and is in `phase/acceptance`, ready for final human
sign-off.

Post a comment requesting approval, using the gate marker:

```
REQUEST-APPROVAL-FROM: @{{ approver }} (The feature is ready for final review.)
```

The planner then waits — it will not advance the epic to `phase/done` until a
human responds with `ACCEPTANCE-DECISION: Approved` (or `Blocked`).

Sign your post with the persona header.
