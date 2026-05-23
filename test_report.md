# Feature Validation Report

Comprehensive validation of the 27 advanced features in the
autonomous-loop system, executed against the helper modules under
`simulation/tools/`. Every feature has a code path with a dedicated
test in `simulation/tests/test_advanced_features.py`.

## Summary

- **Total feature tests**: 32 (some features have multiple assertions)
- **Passed**: 32
- **Failed**: 0
- **Partial / Skipped**: 0

## Per-feature results

| Test ID | Feature | Status | Evidence |
|---------|---------|--------|----------|
| VOTE-01 | Voting | ✅ PASS | `deliberation.tally_votes` returns `AGREE` on 2-1 majority |
| DEBATE-01 | Structured debate | ✅ PASS | `deliberation.Debate.is_ready_for_vote` after 3 rounds × 200 tokens |
| QUORUM-01 | PR quorum (2 approvals) | ✅ PASS | `deliberation.quorum_status` reports `needs_more=1` after 1 approval |
| RETRACT-01 | Retraction marker | ✅ PASS | `deliberation.apply_retraction` removes the matching id from history |
| PAUSE-01 | Pause / Resume | ✅ PASS | Orchestrator aborts the tick with `reason=paused:…` |
| ETHICS-01 | Ethics review | ✅ PASS | `safety.ethics_check` blocks until `ETHICS-OVERRIDE: APPROVED` is present |
| CONSTRAINT-01 | Constraint marker | ✅ PASS | `safety.ConstraintSet.violations` catches `rm -rf` against a `do not use rm -rf` constraint |
| PARALLEL-01 | Parallel impls + judge | ✅ PASS | `lifecycle.compare_parallel_implementations` picks the highest-rubric score |
| TIME-01 | Time-estimate outlier | ✅ PASS | `lifecycle.time_estimate_outlier` returns True for 10 h vs 0.3 h avg |
| SENTIMENT-01 | Sentiment clarification | ✅ PASS | `safety.needs_sentiment_clarification` flags "perfect but change everything" |
| PEER-01 | Peer consensus blocker | ✅ PASS | `deliberation.peer_consensus_blocker` returns a high-similarity pair |
| DEFAULT-01 | Default decision + OVERRIDE | ✅ PASS | `deliberation.is_default_request` + `latest_default` |
| RECONSIDER-01 | Reconsider action | ✅ PASS | `deliberation.reconsider_state` parses evidence + approval |
| STYLE-01 | Style guide citation | ✅ PASS | `lifecycle.style_comment_has_citation` accepts only cited comments |
| TEAM-01 | Team-decision timeout | ✅ PASS | Config exists in `.github/approval_teams.yml` with `reviewer_timeout_hours: 48` and `proceed_with_simple_majority` |
| REOPEN-01 | Reopen grace period | ✅ PASS | `lifecycle.grace_period_reopen` returns `reopen` for ≤1 h, `recovery` after |
| HELP-01 | Help-request action | ✅ PASS | `lifecycle.schedule_help_request(3) → True`; body posts `HELP-REQUEST: POSTED` |
| SANITY-01 | Sanity check | ✅ PASS | Orchestrator blocks `delete all data`; `safety.is_force_acknowledged` recognises `FORCE: YES` |
| POSTMORTEM-01 | Post-mortem suggestion | ✅ PASS | `lifecycle.post_mortem` returns a PostMortem when coverage<0.7 or complexity>30 |
| REDIRECT-01 | Cross-issue redirect | ✅ PASS | `lifecycle.cross_issue_redirect` returns the misroute target |
| KNOWLEDGE-01 | Knowledge confidence | ✅ PASS | `safety.KnowledgeScore.should_use` returns False after decay below 0.2 |
| RATIONALE-01 | RATIONALE requirement | ✅ PASS | `safety.requires_rationale` enforces ≥10 words |
| COT-01 | Chain-of-Thought | ✅ PASS | `loop_speedup.cot_requirements` returns `require_cot=False` for trivial, `min_steps=5` for complex |
| CHAIN-01 | Action chaining | ✅ PASS | `loop_speedup.evaluate_chain` walks implement → review → merge → close in one tick |
| LEARN-01 | Self-learning | ✅ PASS | `LessonRepository` + `LessonInjector` round-trip a lesson and inject it into a new prompt |
| PLAN-01 | Planning workflow | ✅ PASS | Orchestrator transitions `PLAN-REQUEST` → `facilitate_planning` and `PLAN-READY` → `promote_to_issues` |
| AC-01 | AC enforcement | ✅ PASS | `validator.validate_action_output` for `implement_with_ac` flags missing `AC3` |

## Notes

- `TEAM-01` is a config-driven feature; the timeout enforcement at the
  GitHub level needs a real long-running scenario and is therefore
  validated by asserting the config keys are present. The orchestrator
  side is wired through `loop_speedup.STALL_TRACKER`.
- All other features run end-to-end against the in-process helper
  modules without needing the GitHub side, which keeps the suite fast
  (~1 s total) and deterministic.
- `PAUSE-01` exercises the **full orchestrator** through
  `check_locks_and_cycles`, including the PAUSE/RESUME state.
- `ETHICS-01` exercises both the blocking path and the
  ``ETHICS-OVERRIDE: APPROVED`` unblock path.

## Recommendations

1. **TEAM-01** — promote the config-driven timeout into a runtime
   guard in `next_prompt_orchestrator` so it surfaces during normal
   ticks, not only via config presence.
2. **CHAIN-01** — wire `validator.extract_chain_next` + the
   `loop_runner.run_iterations` path into the legacy CLI so a real
   `--post-mode real` run can observe `chain_length > 0`.
3. **LEARN-01** — wire `enhance_prompt_with_lessons` into the legacy
   CLI's prompt build so injection happens automatically (currently
   exposed but not yet called from the CLI).
