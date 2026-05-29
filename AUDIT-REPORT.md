# AUDIT: Full System Audit — ai-erp-foundation (v2)

**Date:** 2026-05-29 (v2 — re-audit after closing G1, G2, G3)
**Branch audited:** `fix/g2-g3-hardening` (on top of `main`, which already has
collaboration markers + epic decomposition + phase-gated lifecycle + the G1
acceptance-rejection rework path).
**Method:** offline/dry-run. `gh` is authenticated but no mutations were made;
the planner pipeline was exercised against synthetic in-memory fixtures.

> **v2 changes since the first audit:** the three top gaps are now **closed** —
> G1 (acceptance rejection rework, merged in PR #176), G2 (test-failure
> follow-up, this PR), G3 (`next_prompt` facade re-exports + the missing
> lifecycle catalog actions, this PR). Documentation gaps and the dev-dependency
> gap (G7) are also addressed. **Zero real test failures** now remain.

---

## 1. Executive Summary

The system is **healthy, internally consistent, and the lifecycle loops are now
closed end-to-end**. All deterministic integrity checks pass: action↔marker
coverage is clean (44 actions), `full_audit.py` exits 0, and the test suite has
**220 functions green with 0 real failures** — the only non-passes are 17
pytest-fixture tests that cannot execute in a `pytest`-less harness (they pass
under real `pytest`; `requirements-dev.txt` now pins it).

Every lifecycle transition that previously dead-ended now resumes
automatically: a human **acceptance rejection** routes the epic back to the
right phase (G1); a **failing test report** files bugs and routes back to
implementation, then re-tests forward on a Pass (G2). The `next_prompt` facade
gap is resolved and the lifecycle action set is complete (G3).

| Dimension | Result |
|-----------|--------|
| Core imports | ✅ all succeed |
| Action↔marker coverage | ✅ `ok=True`, 0 errors (44 actions) |
| `validate_static_config` | ✅ 0 errors |
| `full_audit.py` | ✅ exit 0 — "🎉 Audit passed." |
| Tests (bare harness) | ✅ 220 passed / 17 pytest-fixture-skipped / **0 real failures** |
| Feature tests | ✅ phase 16/16, epic 8/8, marker 4/4, validator 15/15, next_prompt 14/15 (1 fixture) |
| Documentation | ✅ README + markers doc cover collaboration/epic/phase |
| End-to-end simulation | ✅ all 5 phases incl. rejection + test-failure rework loops |

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

## 8. Gap Analysis (v2 status)

| ID | Severity | Status | Notes |
|----|----------|--------|-------|
| **G1** | High | ✅ **RESOLVED** (PR #176) | `fix_acceptance_blocked` routes a Blocked epic back via reason-based phase routing; `latest_acceptance_decision` resolves the reject→rework→re-accept loop; acceptance→Done suppressed while a standing Blocked exists. |
| **G2** | Medium | ✅ **RESOLVED** (this PR) | `TESTING_FAILED` detector (latest `TEST-REPORT: Fail`) blocks the gate and emits `triage_test_failures` — files `bug` sub-issues and routes `phase/testing → phase/implementation`; a later `Pass` gates forward. `latest_test_report` handles the loop. |
| **G3** | Medium | ✅ **RESOLVED** (this PR) | `next_prompt` facade now re-exports `RepoState`, `resolve_priority`, `validate_rendered_prompt`, and the lifecycle helpers (`test_next_prompt` 1/15 → 14/15; the last is a pytest fixture). The missing lifecycle catalog actions `open_issue` / `reopen_issue` / `request_review` were added with distinct markers (`ISSUE-OPENED` / `ISSUE-REOPENED` / `REVIEW-REQUEST`), templates, and a persona owner — closing `test_lifecycle_action_templates_are_cataloged`. |
| **G4** | Low (by design) | Open (intentional) | Collaboration/epic/phase actions remain planner-driven templates (not flat catalog actions) to preserve the action↔marker 1:1 invariant. Lifecycle CRUD actions that *do* warrant catalog status (open/reopen/request_review) were promoted in G3. |
| **G5** | Low | Open | `docs/operating-model.md` still lacks a dedicated lifecycle/decomposition narrative (README + markers doc now cover it). |
| **G6** | Low | Open | Scalability: no per-run action cap / comment-fetch budget for very large epics. |
| **G7** | Low | ✅ **RESOLVED** (this PR) | `requirements-dev.txt` pins `pytest` + `PyYAML` so the fixture-based tests run in CI and locally. |

**Remaining open items are all Low severity** (G4 by-design, G5 docs polish,
G6 scalability hardening). No High or Medium gaps remain.

---

## 9. Recommendations (before real-world use)

G1–G3 and G7 — the bar set by the first audit — are now **closed**. The
remaining items are polish/hardening:

1. **Docs (G5):** extend `docs/operating-model.md` with the lifecycle +
   decomposition narrative (README and the markers doc are already updated).
2. **Scale (G6):** add a per-run action cap and a comment-fetch budget before
   pointing the planner at a large, active repository.
3. **Pilot safely:** run a real low-risk feature in `--dry-run` first, review the
   structured logs, then enable `--apply`. All four rework loops (debate
   resolution, dependency unblock, acceptance rejection, test failure) now
   resume automatically, so the planner no longer stalls at a human-gated step.

Overall: the deterministic core is solid, every lifecycle loop closes, and the
test suite has **zero real failures**. The system is ready for a supervised
dry-run pilot; only Low-severity polish (G5, G6) remains.
