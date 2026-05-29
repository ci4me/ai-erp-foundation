---
id: implement-scenario
description: Add the next missing simulation scenario YAML
---

## Action: Implement Simulation Scenario `{{scenario_id}}`

The next missing scenario from the catalog is `simulation/scenarios/{{scenario_id}}.yml`.

### Scenario schema

```yaml
{{scenario_schema}}
```

### Existing scenario example

```yaml
{{scenario_example}}
```

## Step-by-step execution

### Step 1: Create a branch

Run:

````bash
git checkout -b "feat/scenario-{{scenario_id}}"
````

### Step 2: Read the schema and existing examples

Run:

````bash
sed -n '1,260p' simulation/scenarios/_schema.yml
sed -n '1,260p' simulation/scenarios/001-suspend-cookie.yml
sed -n '1,260p' simulation/scenarios/002-docs-only.yml
````

### Step 3: Write `simulation/scenarios/{{scenario_id}}.yml`

The file must follow `_schema.yml`. Include:

- `id: {{scenario_id}}`
- `status: active`
- `mock_pr` with `title`, `body`, and `diff`
- `planted_flaws` with stable IDs
- `personas` with expected verdicts and `must_catch`
- `expected_overall_verdict`
- `pass_threshold`

### Step 4: Validate locally

Run:

````bash
python simulation/run.py --mode dry-run
python -m pytest simulation/tests
````

### Step 5: Commit, push, and open PR

Run:

````bash
git status --short
git add "simulation/scenarios/{{scenario_id}}.yml"
git commit -m "feat(simulation): add scenario {{scenario_id}}

Adds scenario {{scenario_id}} to expand prompt-regression coverage.

Co-Authored-By: [YOUR MODEL NAME] <noreply@example.com>"
git push -u origin "feat/scenario-{{scenario_id}}"
gh pr create --repo "{{repo}}" \
  --title "feat(simulation): scenario {{scenario_id}}" \
  --body "Adds simulation scenario \`{{scenario_id}}\`.

## Acceptance criteria
- [ ] Scenario validates against simulation/scenarios/_schema.yml
- [ ] Dry-run mode passes
- [ ] Planted flaws are explicit and evidence-bound

## Required reviews
- Prism (PromptOps)
- Tessa (Test Lead)
- Theo (Architect)
- Vera (Risk)
- Rhea (Release)
- Human sign-off: `approved for operating-model amendment per docs/amendment-policy.md`
" \
  --label "risk:high,area:agent-governance,area:ci,ready-for-review"
````

### Step 6: Post end-of-run summary to Epic #1

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-scenario-{{scenario_id}}"
cat > "/tmp/scenario-{{scenario_id}}-summary.md" <<SUMMARY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (implement_scenario)
Self-review conflict: Yes
Run-ID: ${RUN_ID}
---

## End-of-run summary

**Iteration:** implement_scenario
**Scenario:** {{scenario_id}}
**File created:** simulation/scenarios/{{scenario_id}}.yml
**Verification:** [COMMAND + RESULT]
**PR opened:** [PASTE PR URL]

**Next expected loop action:** rerun `next_prompt.py`; it should select the scenario PR for review.
SUMMARY
gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/scenario-{{scenario_id}}-summary.md"
````


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
SCENARIO-IMPLEMENTATION: PR_OPENED
```

Allowed values: `PR_OPENED`, `BLOCKED`.
