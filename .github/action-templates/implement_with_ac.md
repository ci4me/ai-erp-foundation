---
id: implement-with-ac
description: Implement a plan issue while covering every acceptance criterion
---

# Implement with Acceptance Criteria

This issue has `PLAN-STATUS: APPROVED` and a list of AC items. You must
explicitly demonstrate coverage for every AC before opening the PR.

## Chain of Thought

Use the per-issue CoT contract from
`simulation.tools.complexity.get_cot_requirements`.

## Required sections in your response

### Acceptance criteria coverage

For each AC in the issue body, write:

- **AC<n>** — explanation of how the code satisfies it.
- **Test** — pytest file + function that verifies the AC.

### Testing performed

List each test command run with its result:

```
TEST-RESULT: PASS  test_costs_api.py::test_add_entry
TEST-RESULT: PASS  test_costs_api.py::test_alert_on_overspend
```

### Implementation

Diff summary, files touched, link to the PR you opened.

## Output markers

```
AC-COVERAGE: POSTED
PLAN-STATUS: IMPLEMENTING
IMPLEMENTATION-COMPLETE: TRUE
```
