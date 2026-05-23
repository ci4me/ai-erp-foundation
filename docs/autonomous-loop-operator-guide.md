# Autonomous Loop Operator Guide

This document is the starting point for an agent that has no memory of prior
sessions. The repository is designed to be run as a GitHub-backed state machine:
issues, pull requests, discussions, milestones, comments, and reviews are the
state store; `simulation/tools/next_prompt.py` is the scheduler.

## Start point

Run exactly one scheduler command:

```bash
python -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --output /tmp/next.md
```

Then execute `/tmp/next.md` from top to bottom. Do not choose your own task.
After the selected action is posted or completed, run `next_prompt.py` again.
The second run must see the marker you posted and move to the next action.

## What happens when a human requests work?

A request such as "Build a new feature to reconcile bank exports" should enter
GitHub as an Issue, not as an ad-hoc chat promise. The loop then proceeds:

```text
Human request
  -> create_issue from `TEAM-REQUEST:` / `CREATE-ISSUE:` marker, or manually-created issue
  -> triage_issue adds labels, risk, owner persona, milestone intent
  -> implement_issue opens a PR
  -> review_pr repeats until required reviewers are present
  -> merge_gate checks release safety
  -> accept_pr records the governance acceptance decision
  -> merge_pr merges only after acceptance + green gate
  -> close_issue closes the linked issue with evidence
  -> close_milestone closes finished milestones
```

A team request starts with one explicit marker. Put it in an issue or Discussion body:

```text
TEAM-REQUEST: Build a new feature to export paid invoices as CSV.
CREATE-ISSUE: Add a weekly spend report to the cost dashboard.
PROMOTE-TO-ISSUE: Convert this Idea Lab thread into scoped implementation work.
```

`next_prompt.py` selects `create_issue`, creates one `needs-triage` issue, then the normal triage/implementation/review loop continues.

If a request is only an idea, not ready work, put it in an Idea Lab Discussion:

```text
Idea request
  -> comment_discussion / generate_ideas
  -> promote_idea only after reaction or product-owner gate
  -> open_issue when promoted
```

## Markers are the state transitions

Every agent-authored GitHub body must have:

1. the YAML persona header;
2. the body required by the action template;
3. exactly the machine marker declared for that action in
   `.github/action-templates/markers.yml`.

Examples:

```text
REVIEW-VERDICT: APPROVE_WITH_CONDITIONS
ACCEPTANCE-DECISION: ACCEPT
PR-STATE: MERGED
ISSUE-STATE: CREATED
ISSUE-STATE: CLOSED
DISCUSSION-STATE: RESOLVED
MILESTONE-STATE: ASSIGNED
VALIDATION-RESULT: PASS
```

The marker is not a decoration. It is the only part the next loop may trust as
state. Prose explains the marker to humans; the marker drives the scheduler.

## How comments stop

The loop must not post endless comments. A surface is terminal when it contains
a terminal marker from `markers.yml`, such as:

```text
DISCUSSION-STATE: RESOLVED
DISCUSSION-STATE: PROMOTED
DISCUSSION-STATE: CLOSED
ACCEPTANCE-DECISION: REJECT
PR-STATE: MERGED
ISSUE-STATE: CLOSED
MILESTONE-STATE: CLOSED
```

After a terminal marker, the next action is either lifecycle cleanup or idle.
Do not add another discussion/review comment unless a newer explicit marker asks
for it, such as `NEEDS-PERSONA:` or `NEEDS-COMMENT:`.

## Verification before posting

Before any real GitHub mutation, write the candidate body to `/tmp/body.md` and
run:

```bash
python -m simulation.tools.agent_output_validator \
  --action <action_id> \
  --persona <persona_id> \
  --body-file /tmp/body.md
```

Posting is forbidden when the validator exits non-zero.

## Automatic GitHub verification

`.github/workflows/agent-output-validation.yml` re-validates signed agent
comments, PR reviews, review comments, and discussion comments. Ordinary human
comments are ignored. Malformed agent output fails CI so the loop can quarantine
or repair it instead of treating prose as state.

## Auditing coverage

Run the tests before packaging or merging loop changes:

```bash
python -m pytest -q
```

Coverage expectations:

- every action in `.github/action-templates/catalog.yml` has a template;
- every action has a marker in `.github/action-templates/markers.yml`;
- every template mentions its marker contract;
- validator tests cover marker inference and required body shape;
- `next_prompt.py` can render a prompt with no unresolved `{{variable}}` tokens.


## Running without `gh`

`next_prompt.py` first tries the real GitHub CLI. If `gh` is unavailable, it falls back to read-only GitHub REST/GraphQL calls using Python stdlib. For sandboxes with no network, use the fixture bridge:

```bash
python -m simulation.tools.run_next_prompt_from_fixture \
  --fixture /tmp/github-state.json \
  --repo ci4me/ai-erp-foundation \
  --post-mode dry-run \
  --output /tmp/next.md
```

The fixture bridge is how a memoryless agent can test loop progression locally: capture live GitHub state with any available connector, run the real scheduler, execute the safe dry-run prompt, update the fixture with the posted marker, and run the scheduler again.
