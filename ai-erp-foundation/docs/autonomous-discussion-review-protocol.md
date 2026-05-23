# Autonomous Discussion, Comment, and Review Protocol

This repository treats GitHub comments as state. Free-form prose is useful for
humans, but the autonomous loop only trusts signed, machine-parseable markers.

## State markers

| Marker | Surface | Meaning | Next loop behavior |
| --- | --- | --- | --- |
| `REVIEW-REQUEST: <persona-id>` | PR comment | A required persona/human review is missing | `next_prompt.py` selects `request_review` or `review_pr` |
| `**Verdict:** APPROVE_WITH_CONDITIONS` | PR review/comment | Persona review exists but may carry conditions | Review history is counted for that persona |
| `RHEA-VERDICT: MERGE_READY` | PR comment/review | Release gate passed | Human/merge action may be selected |
| `ACCEPTANCE-DECISION: ACCEPT` | PR comment | PR may be merged if CI/mergeability still pass | `merge_pr` may be selected |
| `ACCEPTANCE-DECISION: REJECT` | PR comment | PR should be closed, not merged | `reject_pr` may be selected |
| `ISSUE-STATE: CLOSED` | Issue comment | Issue can be closed with a reason | `close_issue` may be selected |
| `DISCUSSION-STATE: PROMOTED` | Discussion comment | Discussion converted to Issue | Stop discussion comments |
| `DISCUSSION-STATE: REJECTED` | Discussion comment | Idea/debate rejected | Stop discussion comments |
| `DISCUSSION-STATE: RESOLVED` | Discussion comment | Answer accepted or decision made | Stop discussion comments |
| `REVIEW-THREAD-STATE: RESOLVED` | PR review thread | Thread has evidence of resolution | Resolve the thread |
| `VALIDATION-RESULT: PASS/FAIL` | Epic/status comment | Validation result from guard | Loop can trust or quarantine action |

## When something needs review

A PR needs review when any required reviewer is absent from GitHub comments or
review submissions. Required reviewers come from the PR body, persona activation
rules, and policy rules for changed paths. The loop should post `REVIEW-REQUEST:`
only when it cannot safely dispatch the reviewer directly.

## When something needs a comment

A Discussion or issue needs a comment when it has an explicit marker such as
`NEEDS-COMMENT:` or `NEEDS-PERSONA:`, or when it is on an active comment surface
such as Idea Lab and the responsible persona has not yet posted a signed answer.

## When comments must stop

Comments must stop when the surface contains a terminal marker:

- `DISCUSSION-STATE: PROMOTED`
- `DISCUSSION-STATE: REJECTED`
- `DISCUSSION-STATE: CLOSED`
- `DISCUSSION-STATE: RESOLVED`
- `DISCUSSION-STATE: ANSWERED`
- `DISCUSSION-STATE: SUPERSEDED`
- `ISSUE-STATE: CLOSED`
- `ACCEPTANCE-DECISION: ACCEPT`
- `ACCEPTANCE-DECISION: REJECT`

After a terminal marker, the next action is a lifecycle mutation, not another
comment.

## Required output shape

Every agent-authored comment/review must start with the YAML persona header:

```yaml
---
Persona: <persona-id or display name>
Role: <role>
Layer: executive | engineering | assurance | knowledge
Model: <model>
Source: <what was read>
Self-review conflict: Yes | No
Run-ID: <timestamp>-<persona>-<surface>
---
```

Then the body must match the selected action template. For example, `review_pr`
requires a verdict, acceptance matrix, blocking findings, non-blocking findings,
required next action, and evidence references.

## Verification

Local check:

```bash
python3 -m simulation.tools.agent_output_validator \
  --body-file /tmp/agent-body.md \
  --persona iris-security \
  --action review_pr
```

GitHub automatic check:

`.github/workflows/agent-output-validation.yml` runs on `issue_comment`,
`pull_request_review`, `pull_request_review_comment`, and `discussion_comment`.
It ignores normal human comments and validates only signed agent outputs or
machine-state markers.
