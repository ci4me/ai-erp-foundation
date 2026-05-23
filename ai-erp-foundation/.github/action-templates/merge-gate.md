---
id: merge-gate
description: Final release gate for a PR
---

## Action: Release Gate PR #{{pr_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Review history:

{{review_history}}

## Steps

1. Re-read PR state, CI checks, review comments, requested changes, and human sign-off.
2. Verify the quorum required by labels and policy.
3. Post `MERGE_READY` only if all gates pass. Otherwise post `BLOCKED` with exact blockers.

```bash
gh pr view "{{pr_number}}" --repo "{{repo}}" --json number,title,labels,reviewDecision,comments,reviews,statusCheckRollup
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-gate-pr{{pr_number}}"
cat > "/tmp/pr-{{pr_number}}-merge-gate.md" <<GATE
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: PR #{{pr_number}} reviews + CI + labels + policy
Self-review conflict: {{self_review_conflict}}
Run-ID: ${RUN_ID}
---

**Verdict:** MERGE_READY | BLOCKED

| Gate | Status | Evidence |
| --- | --- | --- |
| Required reviewers | PASS/FAIL | [comment URLs] |
| CI checks | PASS/FAIL | [check names] |
| Human sign-off if required | PASS/FAIL/N/A | [comment URL or MISSING] |
| Unresolved blockers | PASS/FAIL | [blockers] |

**Exact blockers:** [list or none]
GATE
if [ "{{post_mode}}" = "real" ]; then gh pr review "{{pr_number}}" --repo "{{repo}}" --comment --body-file "/tmp/pr-{{pr_number}}-merge-gate.md"; else echo "DRY-RUN merge gate"; fi
```
