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
