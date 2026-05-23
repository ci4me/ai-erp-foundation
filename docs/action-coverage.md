# Action Coverage

The action catalog is the loop's menu. `next_prompt.py` may select any cataloged
action, so every action needs all of the following:

1. a catalog entry in `.github/action-templates/catalog.yml`;
2. a prompt template in `.github/action-templates/*.md`;
3. a marker spec in `.github/action-templates/markers.yml`;
4. a primary/support persona in `.github/agent-prompts/*.md` when the action is persona-owned;
5. validator coverage in `simulation.tools.agent_output_validator` or the generic marker check;
6. tests proving static config and marker coverage.

Run all checks:

```bash
python3 -m pytest -q
python3 - <<'PY'
from simulation.tools import next_prompt
errors = next_prompt.validate_static_config()
if errors:
    raise SystemExit("\n".join(errors))
print("static config ok")
PY
```

## Current covered areas

- PR lifecycle: review, request review, merge gate, accept, reject, merge.
- Issue lifecycle: create from team request, open, triage, implement, close, reopen, follow-up.
- Milestones: create, assign, close.
- Discussions: comment, generate ideas, promote idea, close discussion.
- Governance: decision records, ratification, audit, security audit, cost review.
- Verification: prompt regression, agent-action validation, status/skip/idle.

## Adding a new action

1. Add it to `catalog.yml` with a priority and template.
2. Add a template with numbered steps and a validation command.
3. Add a marker spec to `markers.yml`.
4. Add the action to a persona frontmatter `actions.primary` or `actions.support`.
5. Add selector logic in `next_prompt.py` if the action should be selected automatically.
6. Run tests.


## Cold-agent execution contract

A cold agent with no chat history should be able to do this:

```bash
python -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --output /tmp/next.md
cat /tmp/next.md
# execute exactly one action from the prompt
python -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --probe-only
```

If the second probe selects the same action for the same object, one of these is true:

1. the agent did not post the required marker;
2. the marker failed validation;
3. the action is intentionally still incomplete, for example another reviewer remains outstanding;
4. the selector is missing a transition and must get a regression test.
