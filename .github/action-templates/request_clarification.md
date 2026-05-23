---
id: request-clarification
description: Ask a human to clarify after an unknown marker was observed
---

## Action: Request Clarification on Issue #{{issue_number}}

Persona: {{persona_name}} (`{{persona_id}}`)

Unknown marker observed: `{{unknown_marker}}`

## Step-by-step execution

### Step 1: List the valid markers for this surface

```bash
python3 -m simulation.tools.marker_registry --print-valid > /tmp/valid-markers.txt 2>/dev/null \
  || python3 - <<'PY'
from simulation.tools import marker_registry
specs = marker_registry.load_marker_specs()
for action_id, spec in sorted(specs.items()):
    print(f"{spec.marker}: {'|'.join(spec.values) or 'free-form'}")
PY
```

### Step 2: Post the clarification request

```bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-$(uuidgen | cut -c1-8)-{{persona_id}}-clarify-{{issue_number}}"
cat > "/tmp/issue-{{issue_number}}-clarify.md" <<CLARIFY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: Issue #{{issue_number}} unknown marker scan
Self-review conflict: No
Run-ID: ${RUN_ID}
---

CLARIFICATION-REQUEST: POSTED issue#{{issue_number}}

Unknown marker '{{unknown_marker}}' was observed in this thread. The loop cannot
infer the next transition without one of the valid markers below.

**Please use one of:** {{valid_markers}}

**Where it was observed:** {{unknown_marker_location}}
CLARIFY

if [ "{{post_mode}}" = "real" ]; then
  gh issue comment "{{issue_number}}" --repo "{{repo}}" --body-file "/tmp/issue-{{issue_number}}-clarify.md"
else
  echo "DRY-RUN: gh issue comment {{issue_number}} --repo {{repo}} --body-file /tmp/issue-{{issue_number}}-clarify.md"
fi
```

### Step 3: Stop

Do not act further on this issue until a human responds with a valid marker.
