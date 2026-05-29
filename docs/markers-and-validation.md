# Markers and Validation

## Why markers exist

Agent comments are not just prose. They are state transitions. A phrase like
"looks good" is ambiguous; a marker such as `ACCEPTANCE-DECISION: ACCEPT` is
parseable and safe for the next loop iteration.

## Marker registry

The canonical marker registry is:

```text
.github/action-templates/markers.yml
```

Every action in `.github/action-templates/catalog.yml` must have one marker
specification in `markers.yml`. The static configuration check fails if an action
is missing a marker or a marker references an unknown action.

To print the registry as a table:

```bash
python3 - <<'PY'
from simulation.tools import marker_registry
print(marker_registry.format_marker_table())
PY
```

## Persona request markers

Separate from the action→output markers above, a persona can place a *request*
marker in an issue/PR body to pull other personas into the loop. These are
**input** markers (they have no catalog action of their own), so they live under
the `request_markers:` section of `markers.yml` and are excluded from the
action↔marker coverage check.

| Marker | Purpose | Example |
|--------|---------|---------|
| `REQUEST-REPLY-FROM: @p1, @p2` | Ask one or more personas to reply | `REQUEST-REPLY-FROM: @mara-product-owner, @tessa-test-lead` |
| `REQUEST-REVIEW-FROM: @persona` | Ask a persona to review a PR | `REQUEST-REVIEW-FROM: @theo-architect` |
| `REQUEST-APPROVAL-FROM: @persona` | Ask a persona for approval | `REQUEST-APPROVAL-FROM: @vera-risk-officer` |
| `QUESTION-TO: @persona? <text>` | Ask a persona a direct question | `QUESTION-TO: @iris-security? Is this endpoint safe?` |

The planner (`scripts/run_planner.py`) treats any of these as the highest-priority
problem (`UNANSWERED_REQUEST`) and generates one reply/review action per *known*
persona that has not already responded — so re-running never double-posts. Only
handles matching a real persona id (from `.github/agent-prompts/*.md`) are
honored; unknown handles and free text are ignored.

## Agent output validation

Before posting a GitHub comment/review/discussion response, write the body to a
file and run:

```bash
python3 -m simulation.tools.agent_output_validator \
  --action review_pr \
  --persona iris-security \
  --body-file /tmp/body.md
```

The validator checks:

- leading YAML persona header;
- required header fields;
- action-specific marker;
- allowed persona verdict;
- required markdown sections for PR reviews and discussion comments;
- unresolved placeholders such as `CHANGE_ME`;
- evidence requirements for reviews.

## GitHub Actions guard

The workflow below validates posted agent-shaped comments automatically:

```text
.github/workflows/agent-output-validation.yml
```

Human comments such as `LGTM` are ignored. Signed agent outputs or comments with
known state markers are validated.

## Marker lifecycle examples

```text
REVIEW-VERDICT: APPROVE_WITH_CONDITIONS
RHEA-VERDICT: MERGE_READY
ACCEPTANCE-DECISION: ACCEPT
PR-STATE: MERGED
ISSUE-STATE: CREATED
ISSUE-STATE: CLOSED
DISCUSSION-STATE: PROMOTED
MILESTONE-STATE: CLOSED
VALIDATION-RESULT: PASS
```

A terminal marker means the loop should not keep commenting on that object unless
a newer explicit reopen/needs marker appears.


## Marker ownership rules

- A PR review must emit `REVIEW-VERDICT:` and a human-readable `**Verdict:**` line.
- Rhea's release gate emits `RHEA-VERDICT:`. It does not merge.
- Acceptance emits `ACCEPTANCE-DECISION:`. `merge_pr` only runs after `ACCEPT`.
- A created issue emits `ISSUE-STATE: CREATED`; a closed issue emits `ISSUE-STATE: CLOSED`; a reopened issue emits `ISSUE-STATE: REOPENED`.
- Discussion comments use `DISCUSSION-STATE:`. Terminal discussion values stop further discussion comments unless a newer `NEEDS-*` marker appears.

The validator rejects unresolved placeholders and malformed action bodies before they become GitHub state.
