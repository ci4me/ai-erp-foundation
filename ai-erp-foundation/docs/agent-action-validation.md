# Agent action validation

The autonomous loop treats GitHub as the state machine. Agents do not signal progress with prose alone; they use signed, machine-readable comments and reviews that `next_prompt.py` can read on the next run.

## Lifecycle markers

### Pull requests

| Marker | Meaning | Next action |
| --- | --- | --- |
| `**Verdict:** APPROVE` | Persona review is complete and non-blocking | Continue remaining required reviews |
| `**Verdict:** APPROVE_WITH_CONDITIONS` | Persona review is complete, but acceptance gate must inspect conditions | Continue reviews, then `accept_pr` decides |
| `**Verdict:** REQUEST_CHANGES` or `BLOCK` | PR is blocked | `address_changes_requested` |
| `ACCEPTANCE-DECISION: ACCEPT PR#N -- reason` | Final gate says PR may merge | `merge_pr` |
| `ACCEPTANCE-DECISION: HOLD PR#N -- reason` | Final gate is not ready | Fix blockers, then rerun |
| `ACCEPTANCE-DECISION: REJECT PR#N -- reason` | PR should close unmerged | `reject_pr` |

### Discussions

| Marker | Meaning | Next action |
| --- | --- | --- |
| `NEEDS-COMMENT: <persona or topic>` | Discussion needs a response | `comment_discussion` |
| `NEEDS-PERSONA: <persona>` | Specific persona must answer | `comment_discussion` for that persona |
| `QUESTION-FOR-PERSONA: <persona>` | Specific persona must answer a question | `comment_discussion` for that persona |
| `DISCUSSION-STATE: RESOLVED` | Discussion is done | Stop commenting |
| `DISCUSSION-STATE: PROMOTED` | Discussion became an issue | Stop commenting |
| `DISCUSSION-STATE: DEFERRED` | Discussion should wait | Stop unless reopened |
| `DISCUSSION-STATE: CLOSED` | Discussion is terminal | Stop commenting |
| `DECISION-RECORDED:` | Decision has been captured elsewhere | Stop commenting |

### Issues

| Marker | Meaning | Next action |
| --- | --- | --- |
| `CREATE-ISSUE:` | Open a bounded follow-up issue | `create_issue` |
| `PROMOTE-TO-ISSUE:` | Convert discussion/review finding into an issue | `create_issue` or `promote_idea` |
| `ISSUE-STATE: READY_TO_CLOSE` | Close the issue after evidence check | `close_issue` |
| `ISSUE-STATE: CLOSED` | Terminal state | Stop |
| `MILESTONE-REQUEST:` | Create or assign a milestone | `create_milestone` / `assign_milestone` |

## When to stop

Stop adding comments when any terminal marker exists and no newer `NEEDS-*` marker appears after it. Stop after posting an end-of-run summary. Do not choose the next task manually; rerun `next_prompt.py` so it can re-read GitHub state.

## Validation layers

1. **Prompt-time validation:** action templates instruct the agent to run `python -m simulation.tools.validate_agent_action` before posting.
2. **Test-time validation:** `pytest` checks that templates render and validators reject malformed examples.
3. **GitHub-time validation:** `.github/workflows/agent-action-validator.yml` runs on PR reviews, issue comments, review comments, discussions, and discussion comments. It skips normal human comments and validates bodies containing agent markers.

## Manual usage

```bash
python -m simulation.tools.validate_agent_action --kind pr-review --persona mara-product-owner --file /tmp/review.md
python -m simulation.tools.validate_agent_action --kind discussion-comment --persona iris-security --file /tmp/comment.md
python -m simulation.tools.validate_agent_action --kind acceptance-decision --file /tmp/acceptance.md --json
python -m simulation.tools.validate_agent_action --kind auto --file /tmp/body.md --json
```

Exit code `0` means valid. Exit code `1` means the action body is malformed and must not be posted. Exit code `2` means the input could not be read or the CLI usage is invalid.
