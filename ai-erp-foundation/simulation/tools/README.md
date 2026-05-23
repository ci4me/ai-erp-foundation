# `simulation/tools/`

Operational tools for the autonomous GitHub loop.

## Tools

| Tool | Purpose |
| --- | --- |
| `next_prompt.py` | Reads GitHub/local state, chooses one action, renders a self-contained prompt from repository templates. |
| `marker_registry.py` | Loads `.github/action-templates/markers.yml` and verifies every action has a parseable state marker. |
| `action_coverage.py` | Static audit that every action/template/marker/persona/scenario contract is covered. |
| `agent_output_validator.py` | Validates a proposed or posted agent comment/review/discussion body. |
| `agent_event_guard.py` | GitHub Actions entrypoint that validates webhook payloads containing agent-shaped output. |
| `arch_snapshot.py` | Captures repository architecture state. |
| `coverage_matrix.py` | Summarizes persona/scenario scorecards. |
| `meta_sage.py` | Optional self-critique tool gated by API key. |

## Normal loop command

```bash
python3 -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation --output /tmp/next.md
```

## Validate an agent body before posting

```bash
python3 -m simulation.tools.agent_output_validator \
  --action review_pr \
  --persona iris-security \
  --body-file /tmp/body.md
```

## Static checks

```bash
python3 -m pytest -q
python3 -m simulation.tools.action_coverage
python3 - <<'PY'
from simulation.tools import next_prompt
errors = next_prompt.validate_static_config()
if errors:
    raise SystemExit("\n".join(errors))
print("static config ok")
PY
```
