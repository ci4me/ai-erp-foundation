# Autonomous Loop Runbook

This repository treats GitHub as the durable state machine for an AI-agent team.
The loop is intentionally simple:

```text
1. Read live GitHub state.
2. Pick exactly one next action.
3. Render that action from repository-owned templates.
4. Execute the prompt exactly.
5. Post one signed, marker-bearing result.
6. Run next_prompt.py again.
```

The loop does **not** remember private chat context. A future agent should be
able to enter the repo cold, run one command, and know what to do.

## Start point

Run this from the repository root:

```bash
python3 -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --output /tmp/next.md
cat /tmp/next.md
```

For a safe rehearsal:

```bash
python3 -m simulation.tools.next_prompt \
  --repo ci4me/ai-erp-foundation \
  --post-mode dry-run \
  --output /tmp/next.md
```

For diagnostics only:

```bash
python3 -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --probe-only
```

## How a human request enters the team

A human request such as:

> Build a new feature to export invoices as CSV.

should become an Issue, not a free-form chat memory. The minimum issue body is:

```markdown
## User request
Build a new feature to export invoices as CSV.

## Acceptance criteria
- [ ] User can export invoices as CSV from the relevant UI/API entrypoint.
- [ ] Export respects tenant/security boundaries.
- [ ] Tests cover happy path and denied access.

## Initial labels
work:feature
needs-triage
```

Then the loop does the rest:

```text
new issue without ready-for-agent
  -> triage_issue
ready-for-agent + work:system-improvement/work:feature
  -> implement_issue
PR opened
  -> review_pr for each required persona
reviews complete
  -> merge_gate
RHEA-VERDICT: MERGE_READY
  -> accept_pr
ACCEPTANCE-DECISION: ACCEPT
  -> merge_pr
PR-STATE: MERGED / ISSUE-STATE: CLOSED
  -> next work item
```

## How the loop keeps going

Every action writes a machine marker. `next_prompt.py` reads those markers on the
next run and advances to the next state. If an agent forgets the marker, the
validator fails and the loop must not trust the output.

## When to stop

The selected prompt always ends after one action. Do not chain tasks manually.
The next step is always to rerun `next_prompt.py` so the loop sees the latest
GitHub state.
