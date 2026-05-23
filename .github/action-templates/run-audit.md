---
id: run-audit
description: Run repository governance/audit tools and post the result
---

## Action: Run Audit for Issue #{{audit_issue_number}}

Live state selected this audit-like issue:

- Issue: #{{audit_issue_number}} - {{audit_issue_title}}
- Labels: {{audit_issue_labels}}

Issue body:

```markdown
{{audit_issue_body}}
```

## Step-by-step execution

### Step 1: Capture current architecture state

Run:

````bash
python -m simulation.tools.arch_snapshot --output "/tmp/ai-erp-arch-snapshot.json"
````

### Step 2: Run scorecard coverage audit

Run:

````bash
python -m simulation.tools.coverage_matrix > "/tmp/ai-erp-coverage-matrix.md"
````

### Step 3: Optional deep self-critique

Only run this if an API key is already present and the budget remains under $5:

````bash
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" python -m simulation.tools.meta_sage > "/tmp/ai-erp-meta-sage.md"
````

If no key is present, write `SKIPPED: ANTHROPIC_API_KEY not set` into the summary.

### Step 4: Build the audit comment

Run:

````bash
RUN_ID="$(date -u +%Y-%m-%dT%H:%M:%SZ)-audit-issue{{audit_issue_number}}"
cat > "/tmp/audit-issue-{{audit_issue_number}}.md" <<REPORT
---
Persona: {{persona_id}}
Role: {{persona_role}}
Layer: {{persona_layer}}
Model: {{persona_model_default}}
Source: arch_snapshot.py + coverage_matrix.py + optional meta_sage.py
Self-review conflict: Yes
Run-ID: ${RUN_ID}
---

AUDIT-STATUS: PASS|FAIL|PARTIAL — CHANGE_ME_to_one_of_those

## Audit report

**Issue:** #{{audit_issue_number}} - {{audit_issue_title}}

## Audit findings

**Commands run:**
- \`python -m simulation.tools.arch_snapshot --output /tmp/ai-erp-arch-snapshot.json\`
- \`python -m simulation.tools.coverage_matrix > /tmp/ai-erp-coverage-matrix.md\`
- [META_SAGE STATUS]

**Findings:**
1. [Finding with evidence]
2. [Finding with evidence]

**Required next action:**
[One concrete next action, or "No action required."]

**Artifacts:**
- /tmp/ai-erp-arch-snapshot.json
- /tmp/ai-erp-coverage-matrix.md
- /tmp/ai-erp-meta-sage.md if generated
REPORT
````

Fill in the findings from the generated files.

### Step 5: Post the audit to the issue and Epic #1

Run:

````bash
gh issue comment "{{audit_issue_number}}" --repo "{{repo}}" --body-file "/tmp/audit-issue-{{audit_issue_number}}.md"
gh issue comment 1 --repo "{{repo}}" --body "Audit iteration completed for issue #{{audit_issue_number}}. See the audit comment for findings."
````
