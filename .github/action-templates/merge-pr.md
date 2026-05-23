---
id: merge-pr
description: Merge a PR after MERGE_READY
---

## TL;DR

Merge PR #{{pr_number}} and post `MERGE-STATUS: COMPLETE`. Only merge if a
valid `RHEA-VERDICT: MERGE_READY` and `ACCEPTANCE-DECISION: ACCEPT` exist on
the latest head SHA. Do not narrate; one comment, one merge.

## Action: Merge PR #{{pr_number}}

Only merge if a valid MERGE_READY gate exists on the latest head SHA and GitHub branch protection allows the merge.

```bash
gh pr view "{{pr_number}}" --repo "{{repo}}" --json number,title,mergeStateStatus,reviewDecision,statusCheckRollup,comments
if [ "{{post_mode}}" = "real" ]; then
  gh pr merge "{{pr_number}}" --repo "{{repo}}" --squash --delete-branch
else
  echo "DRY-RUN: gh pr merge {{pr_number}} --repo {{repo}} --squash --delete-branch"
fi
```

## Optional Chaining

After a successful merge the loop can close the linked issue inline:

```
CHAIN-NEXT: close_issue
```

Skip the chain when the issue should remain open for follow-up work
(for example, when the merge only landed part of a multi-PR plan).
