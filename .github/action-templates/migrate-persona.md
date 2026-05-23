---
id: migrate-persona
description: Create the next missing persona prompt from the canonical contract
---

## Action: Migrate Missing Persona `{{target_persona_id}}`

The live state says the next missing persona prompt is:

- Persona id: `{{target_persona_id}}`
- Suggested display name: {{target_persona_name}}
- Suggested role: {{target_persona_role}}
- Suggested lens: {{target_persona_lens}}

The persona file must become `.github/agent-prompts/{{target_persona_id}}.md`.

### Canonical frontmatter contract from `.github/agent-prompts/README.md`

```yaml
{{persona_frontmatter_contract}}
```

### Reference persona files to read first

{{persona_reference_files}}

### Universal preamble available to reviewer personas

```markdown
{{preamble_text}}
```

## Step-by-step execution

### Step 1: Create a branch

Run:

````bash
git checkout -b "feat/persona-{{target_persona_id}}"
````

### Step 2: Read the contract and examples

Run:

````bash
sed -n '1,220p' .github/agent-prompts/README.md
sed -n '1,220p' .github/agent-prompts/ari-orchestrator.md
sed -n '1,260p' .github/agent-prompts/theo-architect.md
````

### Step 3: Fetch source history for this persona

Run:

````bash
gh issue view 5 --repo "{{repo}}" --comments
gh api graphql -f owner="${REPO_OWNER:-ci4me}" -f name="${REPO_NAME:-ai-erp-foundation}" -f number=2 -f query='
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    discussion(number:$number) {
      title
      body
      comments(first:50) {
        nodes { author { login } body createdAt url }
      }
    }
  }
}'
````

Use Discussion #2 and Issue #5 as historical source material. Do not invent authority that the history does not support.

### Step 4: Create `.github/agent-prompts/{{target_persona_id}}.md`

Use this exact skeleton, then replace bracketed text with evidence from the fetched history:

````markdown
---
id: {{target_persona_id}}
name: {{target_persona_name}}
role: {{target_persona_role}}
layer: [executive | engineering | assurance | knowledge]
version: 0.1.0
model_default: claude-sonnet-4-6
model_alternates:
  - claude-opus-4-7-1m
lens: {{target_persona_lens}}
verdict_enum:
  - APPROVE
  - APPROVE_WITH_CONDITIONS
  - REQUEST_CHANGES
  - COMMENT
  - ABSTAIN
activates_on:
  - "*"
actions:
  primary:
    - [choose_action_ids_from_.github/action-templates/catalog.yml]
  support:
    - [choose_support_action_ids_from_.github/action-templates/catalog.yml]
context_refs:
  review_pr:
    - [docs/or/path/this/persona/needs.md]
forbidden_paths:
  - ".github/agent-prompts/**"
  - ".github/workflows/**"
context_pack: standard
inherits_preamble: true
last_validated_against_model: claude-sonnet-4-6
last_sim_pass: {{generated_at}}
frozen_sha: ""
owner: ci4me
---

# {{target_persona_name}} - {{target_persona_role}}

(Universal Reviewer Preamble auto-prepended if `inherits_preamble: true`.)

## Mission

[2-4 sentences. What this persona protects.]

## Lens

[What this persona sees that others might miss.]

## Authority

You may:

- [Allowed action 1]
- [Allowed action 2]

Request changes for:

- [Blocking condition 1]
- [Blocking condition 2]

## Forbidden

- [Forbidden action 1]
- [Forbidden action 2]
- Touching `.github/agent-prompts/**` unless the operating model explicitly authorizes this persona to edit prompts.

## Inputs

- The PR diff.
- Linked issue acceptance criteria.
- Relevant operating-model docs.

## Output

```
**Verdict:** APPROVE | APPROVE_WITH_CONDITIONS | REQUEST_CHANGES | COMMENT | ABSTAIN

**Assessment:** (2-3 sentences)

**Acceptance matrix:**
| Criterion | Status | Evidence (path:line) |
| --- | --- | --- |

**Blocking findings:**
1. ...

**Non-blocking findings:**
1. ...

**Required next action:**
[one sentence]
```

## Hard rules specific to {{target_persona_name}}

1. [Rule from history]
2. [Rule from history]
````

### Step 5: Validate the prompt file

Run:

````bash
python - <<'PY'
from pathlib import Path
import yaml
path = Path(".github/agent-prompts/{{target_persona_id}}.md")
text = path.read_text()
frontmatter = text.split("---", 2)[1]
data = yaml.safe_load(frontmatter)
required = ["id", "name", "role", "layer", "model_default", "lens", "verdict_enum", "activates_on", "forbidden_paths", "context_pack", "inherits_preamble", "owner"]
missing = [key for key in required if key not in data]
assert not missing, missing
assert data["id"] == "{{target_persona_id}}"
assert data.get("actions", {}).get("primary") or data.get("actions", {}).get("support"), "persona must declare actions.primary or actions.support"
print("persona frontmatter ok")
PY
````

### Step 6: Commit, push, and open PR

Run:

````bash
git status --short
git add ".github/agent-prompts/{{target_persona_id}}.md"
git commit -m "feat(persona): migrate {{target_persona_id}}

Adds {{target_persona_name}} as a canonical persona prompt under .github/agent-prompts.

Co-Authored-By: [YOUR MODEL NAME] <noreply@example.com>"
git push -u origin "feat/persona-{{target_persona_id}}"
gh pr create --repo "{{repo}}" \
  --title "feat(persona): {{target_persona_name}} ({{target_persona_role}})" \
  --body "Migrates \`{{target_persona_id}}\` into \`.github/agent-prompts/\` using the canonical frontmatter contract.

## Acceptance criteria
- [ ] Persona frontmatter matches .github/agent-prompts/README.md
- [ ] Persona body defines Mission, Lens, Authority, Forbidden, Inputs, Output, hard rules
- [ ] Prompt cites source history from Issue #5 / Discussion #2 where applicable

## Required reviews
- Prism (PromptOps)
- Theo (Architect)
- Vera (Risk)
- Rhea (Release)
- Human sign-off: `approved for operating-model amendment per docs/amendment-policy.md`
" \
  --label "risk:high,area:agent-governance,agent:promptops,ready-for-review"
````

### Step 7: Post end-of-run summary to Epic #1

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-persona-{{target_persona_id}}"
cat > "/tmp/persona-{{target_persona_id}}-summary.md" <<SUMMARY
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: autonomous-loop iteration (migrate_persona)
Self-review conflict: Yes
Run-ID: ${RUN_ID}
---

## End-of-run summary

**Iteration:** migrate_persona
**Persona migrated:** {{target_persona_id}}
**File created:** .github/agent-prompts/{{target_persona_id}}.md
**PR opened:** [PASTE PR URL]

**Next expected loop action:** rerun `next_prompt.py`; it should select the new PR for persona review.
SUMMARY
gh issue comment 1 --repo "{{repo}}" --body-file "/tmp/persona-{{target_persona_id}}-summary.md"
````
