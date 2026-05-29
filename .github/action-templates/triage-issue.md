---
id: triage-issue
description: Triage an issue into actionable autonomous-loop work
---

## Action: Triage Issue #{{issue_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Issue labels: {{issue_labels}}

```markdown
{{issue_body}}
```

## Steps

1. Read the issue body and identify the user outcome, risk, acceptance criteria, and likely owner persona.
2. Use the persona action catalog above to choose required reviewers from persona-declared capabilities, not from hardcoded names.
3. If details are missing, post `NEEDS_TRIAGE`; otherwise post `READY_FOR_AGENT`.
4. In `post_mode=real`, add labels only after the signed triage comment is valid.

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-triage-{{issue_number}}"
cat > "/tmp/issue-{{issue_number}}-triage.md" <<TRIAGE
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Issue #{{issue_number}} + labels
Self-review conflict: No
Run-ID: ${RUN_ID}
---

**Verdict:** READY_FOR_AGENT | NEEDS_TRIAGE | BLOCKED

**Risk:** [risk:low|risk:medium|risk:high|risk:critical]
**Owner persona:** [persona id from persona frontmatter capabilities]
**Required reviewers:** [persona ids from frontmatter capabilities]

**Acceptance criteria check:**
1. [criterion or MISSING]

**Required next action:** [one sentence]
TRIAGE
python - <<'PY'
from pathlib import Path
text = Path("/tmp/issue-{{issue_number}}-triage.md").read_text()
for bad in ["READY_FOR_AGENT |", "[", "]"]:
    if bad in text:
        raise SystemExit(f"Unresolved placeholder: {bad}")
print("triage body validation passed")
PY
if [ "{{post_mode}}" = "real" ]; then
  gh issue comment "{{issue_number}}" --repo "{{repo}}" --body-file "/tmp/issue-{{issue_number}}-triage.md"
else
  echo "DRY-RUN: gh issue comment {{issue_number}} --repo {{repo}} --body-file /tmp/issue-{{issue_number}}-triage.md"
fi
```


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
TRIAGE-DECISION: READY_FOR_AGENT
```

Allowed values: `READY_FOR_AGENT`, `NEEDS_TRIAGE`, `BLOCKED`, `DEFER`.
