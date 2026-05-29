# Action: triage_test_failures

You are {{ persona }}. Epic #{{ issue_number }} is in `phase/testing` and its
latest `TEST-REPORT` is **Fail** — the testing gate is blocked.

Steps:

1. Read the failing `TEST-REPORT: Fail (details: ...)` comment.
2. For each **distinct** failure, ensure a tracking issue exists: open one
   labelled `bug` with `Parent epic: #{{ issue_number }}` in its body (skip
   failures that already have such a bug issue — be idempotent).
3. Route the epic back to implementation so the bugs get fixed:
   - remove `phase/testing`, add `phase/implementation`;
   - post the transition marker below.
4. After the fixes merge, the epic re-enters `phase/testing` and a fresh
   `TEST-REPORT: Pass` will gate it forward to acceptance.

```
PHASE-CHANGE: phase/testing -> phase/implementation (reason: TEST-REPORT: Fail — bugs filed for rework)
```

Sign your post with the persona header.
