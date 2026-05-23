---
id: verify-implementation
description: Verify every AC after the implementing PR merged
---

# Verify Implementation Against Plan

Runs after a PR linked to a `PLAN-STATUS: IMPLEMENTING` issue merged.
Check that every AC is *actually* satisfied — not just claimed.

## Steps

1. Fetch the issue body, extract the `- [ ] AC<n>:` lines.
2. For each AC, run a check:
   - If the AC names a CLI command, run it and capture the output.
   - If the AC names an endpoint, hit it (use `curl` against a local
     server if available) and assert the response.
   - If the AC names a test, run that test directly.
3. Aggregate per-AC results.

## Output

If every AC passes:

```
AC-DONE: ALL
PLAN-STATUS: DONE
ISSUE-CLOSED: DONE
```

If any AC fails, reopen the issue with:

```
AC-DONE: PARTIAL
PLAN-STATUS: DRAFT
```

and a comment naming the failing ACs and the next fix.

## Required output marker

```
AC-DONE: ALL|PARTIAL|FAILED
```
