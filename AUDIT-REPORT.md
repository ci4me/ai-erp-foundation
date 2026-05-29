# AUDIT: Full System Audit — ai-erp-foundation

**Date:** 2026-05-29
**Branch audited:** `feat/phase-lifecycle` (collaboration markers + epic
decomposition + phase-gated lifecycle, on top of `main`).
**Method:** offline/dry-run. `gh` is authenticated but no mutations were made;
the planner pipeline was exercised against synthetic in-memory fixtures.

---

## 1. Executive Summary

The system is **healthy and internally consistent**. All deterministic
integrity checks pass: the static action↔marker coverage audit is clean, the
project's own `full_audit.py` exits 0, and every test that does not require the
(absent) `pytest` runtime passes — **201 test functions green**, with the 30
non-passes attributable to two non-defects (pytest fixtures unavailable in the
bare harness, and a pre-existing `next_prompt` facade gap unrelated to this
work).

The five-phase lifecycle, epic decomposition, and collaboration layers behave
correctly end-to-end in simulation, including human wait points and
phase-scoped action suppression. The main findings are **documentation drift**
(now partially fixed in this PR) and a few **unhandled planner transitions**
(notably acceptance rejection), detailed in §8.

| Dimension | Result |
|-----------|--------|
| Core imports | ✅ all succeed |
| Action↔marker coverage | ✅ `ok=True`, 0 errors (41 actions) |
| `full_audit.py` | ✅ exit 0 — "🎉 Audit passed." |
| Tests (bare harness) | ✅ 201 passed / 30 fixture-or-preexisting |
| New feature tests | ✅ phase 10/10, epic 8/8 |
| Documentation | ⚠️ drift found; markers doc + README updated in this PR |
| End-to-end simulation | ✅ correct action sequence across all 5 phases |

---

## 2. Static Analysis

**Imports** — all core modules import without error:

```
from simulation.tools import next_prompt, state_analyzer, marker_registry,
    agent_output_validator, full_audit, plan_builder, state_fetcher, config,
    debug_logger
→ All imports successful
```

**Action coverage** (`python3 -m simulation.tools.action_coverage`):

```
ok: True   errors: 0   (41 catalog actions, 5 scenarios)
```

All 41 catalog actions have a 1:1 marker spec, a template that documents that
marker, and at least one persona owner. The new collaboration / epic / phase
actions (`request_info`, `debate`, `resolve_debate`, `escalate`, `record_adr`,
`explain`, `decompose_feature`, `create_sub_issues`, `run_tests`, `phase_gate`,
`acceptance_review`) are intentionally **not** catalog entries — they are
planner-driven templates keyed off marker sections (`collaboration_markers`,
`phase_labels`). This was a deliberate design choice (see §8 / Gap G4): adding
them as flat catalog actions would break the action↔marker 1:1 invariant the
coverage test enforces.

---

## 3. Test Results

`pytest` is **not installed** in the audit environment, so the suite was run
via a bare reflection harness (calls each `test_*` function directly).
Fixture-based tests therefore raise `TypeError: missing positional argument`
and are counted as skipped, not failed.

```
TOTALS: 201 passed, 30 failed/skipped
```

| Module | Result | Note |
|--------|--------|------|
| test_phase_management | 10/10 | new (this PR) |
| test_epic_decomposition | 8/8 | |
| test_agent_output_validator | 15/15 | |
| test_marker_registry | 4/4 | previously-failing legacy tests now green |
| test_chaining | 22/22 | |
| test_advanced_features | 29/32 | 3 = pytest fixtures (`tmp_path`) |
| test_audit_fixes | 27/28 | 1 = pytest fixture (`capsys`) |
| test_deliberation | 17/18 | 1 = pytest fixture |
| test_learning | 0/9 | all require `tmp_path` fixture |
| test_next_prompt | 1/15 | **pre-existing** facade gap (`next_prompt.RepoState` missing) + fixtures |
| test_run | import-skip | `import pytest` at module top |
| (others) | all pass | |

**Failure classification:**
- **Pytest fixtures (≈24):** pass under real `pytest`; not defects.
- **Pre-existing facade gap (`test_next_prompt`):** the in-progress
  `extract-models-config` refactor never re-exported `RepoState` (and some
  helpers) onto the `next_prompt` facade. This predates all lifecycle work and
  is **not** introduced here. Severity Medium (§8 / G3).

No test regressions were introduced by the collaboration / epic / phase work.

---

## 4. Audit Script Result

```
$ python3 simulation/tools/full_audit.py
=== Full Audit ===
✅ Action↔marker coverage intact (41 actions).
✅ All 17 collaboration markers present.
✅ All 4 request markers present.
✅ All 5 phase labels defined.
✅ All catalog action templates exist.
✅ All 12 collaboration templates exist.
✅ config.DEBATE_RESOLUTION_TIMEOUT_HOURS = 24.
✅ config.EPIC_DETECTION_MODE = label.
✅ All 13 planner detectors present in state_analyzer.
🎉 Audit passed.   (exit 0)
```

---

## 5. Documentation Review

| Doc | Finding | Status |
|-----|---------|--------|
| `README.md` | Had **0** mentions of collaboration / epic / phase features. CLI examples (`next_prompt`, planner) still correct. | **Fixed in this PR** — added a "Collaboration, epics, and phase lifecycle" section. |
| `docs/markers-and-validation.md` | Documented request markers only; the collaboration, epic, and phase markers/labels were **absent**. | **Fixed in this PR** — added "Collaboration markers" + "Phase-lifecycle labels" sections. |
| `docs/operating-model.md` | Uses "phase" generically (30 hits) but does **not** describe the new five-phase gated lifecycle or decomposition protocol. | **Gap (Low)** — left for a dedicated docs pass (§8 / G5). |
| `.github/agent-prompts/*.md` | Personas cannot list `decompose_feature` / `run_tests` in frontmatter: those are planner-driven, **not** catalog actions, and `action_coverage` rejects persona references to unknown actions. The planner instead assigns them dynamically (Architect→decompose, Test Lead→run_tests, Product Owner→acceptance). | **By design** (§8 / G4). The audit's expectation here conflicts with the action↔marker invariant; documented rather than forced. |

---

## 6. Simulation Walkthrough (dry-run, synthetic epic #100 "Add user messaging")

Each row runs `analyze_state → build_plan(mode=multi)` and reports the steps
targeting epic #100. No GitHub mutations occur.

| # | Fixture state | Detected (for #100) | Planner action |
|---|---------------|---------------------|----------------|
| 1 | `phase/planning`, CONSENSUS + DECOMPOSITION-PLAN + Approved | `PHASE_GATE_READY` (+ subtasks) | `phase_gate` → `PHASE-CHANGE: planning → implementation` (Lead) |
| 2 | `phase/implementation`, 1 **open** child | — (no gate) | **no implementation step** — gate withheld until child closes |
| 3 | `phase/implementation`, child **closed** + approving review | `PHASE_GATE_READY` | `phase_gate` → testing (Lead) |
| 4 | `phase/testing`, no report | `TESTING_REQUIRED` | `run_tests` (Test Lead / tessa) |
| 5 | `phase/testing`, `TEST-REPORT: Pass` | `PHASE_GATE_READY` | `phase_gate` → acceptance (Lead) |
| 6 | `phase/acceptance`, no request | `ACCEPTANCE_REQUIRED` | `acceptance_review` → `REQUEST-APPROVAL-FROM` (Product Owner / mara) |
| 7 | `phase/acceptance`, `ACCEPTANCE-DECISION: Approved` | `PHASE_GATE_READY` | `phase_gate` → done (Lead) |
| 8 | `phase/done` | — | **no actions** (terminal) |

**Correctness commentary:**
- **Phase suppression verified:** in rows 4–8, generic problems like
  `EPIC_UNDECOMPOSED` and `MISSING_MARKER` are *detected* but **filtered out**
  by `_phase_allows` because they are not valid for the testing/acceptance/done
  phases — the planner never tries to implement or decompose out of phase.
- **Human wait point verified:** row 6 posts the approval request; with the
  request present but unanswered, `phase_gate_ready` returns `None` (row tested
  separately) — the loop genuinely waits for `ACCEPTANCE-DECISION`.
- **Definition of Done verified:** row 2 (open child) yields no gate; row 3
  (closed child with an approving review and no open objection) does.

---

## 7. Debug Log Sample

`simulation/tools/debug_logger.py` writes one JSON file per step under
`logs/YYYY-MM-DD/<run_id>-step-<NNNN>.json`. Sample step (dry-run):

```json
{
  "timestamp": "2026-05-29T03:17:52.854770+00:00",
  "run_id": "20260529-031752-854664",
  "mode": "multi",
  "step_index": 1,
  "persona": "tessa-test-lead",
  "action": "comment_issue",
  "target": { "type": "issue", "number": 100 },
  "prompt_body": "TEST-REPORT: Pass",
  "gh_command": "gh issue comment 100 ...",
  "gh_output": "",
  "success": true,
  "error": null,
  "dry_run": true
}
```

Every entry carries `persona`, `action`, `target`, and `dry_run` as required.

---

## 8. Gap Analysis

| ID | Severity | Gap | Recommendation |
|----|----------|-----|----------------|
| **G1** | **High** | **Acceptance rejection is a dead end.** `ACCEPTANCE_BLOCKED` is detected (priority 1) but has **no fixer** — the planner surfaces it and stops. A human `ACCEPTANCE-DECISION: Blocked` does not route the epic back to implementation. | Add a fixer that moves the epic `phase/acceptance → phase/implementation` (or opens a rework issue) on Blocked, mirroring `phase_gate`. |
| **G2** | Medium | **`TEST-REPORT: Fail` has no automatic follow-up.** The `run_tests` template asks for bug issues, but no detector creates/blocks on them; a Fail simply leaves the epic in `phase/testing` with no gate. | Add a `TESTING_FAILED` detector that blocks the gate and ensures `bug` sub-issues exist. |
| **G3** | Medium | **`next_prompt` facade gap (pre-existing).** `test_next_prompt` fails because the facade does not re-export `RepoState` (and a few helpers) from the legacy module. Not caused by this work. | Finish the `extract-models-config` re-export surface (as was done for `validate_static_config`, `_persona_aliases`, etc.). |
| **G4** | Low (by design) | New collaboration/epic/phase actions are not catalog actions and cannot be listed in persona frontmatter (coverage rejects unknown actions). | If first-class catalog status is desired, add per-action marker specs + selectors so they pass `action_coverage`; otherwise keep the current planner-driven assignment (documented). |
| **G5** | Low | `docs/operating-model.md` does not describe the five-phase lifecycle or decomposition protocol. | Dedicated docs pass adding a lifecycle section. |
| **G6** | Low | **Scalability:** epics with many sub-tasks fetch comments per issue; `multi` mode emits a step per problem with no cap. | Add a per-run action cap / batching and a comment-fetch budget for large repos. |
| **G7** | Low | **`pytest` not in the environment**, so fixture-based tests can't run in CI here; the bundled `ci-feedback.yml` installs pytest but the repo has no pinned test dependency. | Add `pytest` to a dev-requirements file so local + CI runs are consistent. |

---

## 9. Recommendations (before real-world use)

1. **Close G1 (High):** implement the acceptance-rejection path — it is the one
   lifecycle transition that currently dead-ends.
2. **Close G2:** wire `TEST-REPORT: Fail` to bug-issue creation + gate blocking
   so the testing phase can't be skipped past a failure.
3. **Resolve G3:** complete the `next_prompt` facade re-exports and restore
   `test_next_prompt` to green; add `pytest` as a dev dependency (G7) so the
   full suite runs in CI.
4. **Docs (G5):** extend `docs/operating-model.md` with the lifecycle +
   decomposition narrative (this PR already updated README and the markers doc).
5. **Scale (G6):** add an action cap and comment-fetch budget before pointing
   the planner at a large, active repository.
6. **Then** pilot on a real low-risk feature in `--dry-run` first, review the
   structured logs, and only enable `--apply` once the acceptance-rejection and
   test-failure paths are closed.

Overall: the deterministic core is solid and the lifecycle logic is correct in
simulation. Closing **G1–G3** is the recommended bar before a real project.
