# Bottleneck Analysis — PHP-ERP Marathon (30 ticks)

Findings ranked by impact on iteration throughput, derived from the
30-tick log + cross-referenced with the 45-iter and 50-iter logs from
earlier in this session.

## Top 3 bottlenecks

### 1. Legacy CLI doesn't consult `DedupeCache` / `StallTracker`

**Evidence**: every batch in this session (45-iter, 100-iter, 30-iter
marathon) showed 60–100 % "diversity-override" rate. The sub-agent had
to bypass `next_prompt`'s first-match selector and rotate targets by
hand. In the marathon batch this was the difference between 30 useful
iterations and ~3 useful iterations.

**Fix**: in `next_prompt_legacy.resolve_priority`, after each selector
returns a candidate, call
`next_prompt_orchestrator.DEDUPE_CACHE.is_duplicate(action, persona,
target)` and skip to the next selector when True. The cache is
process-local and already wired into the orchestrator guard chain —
the legacy CLI just doesn't read it.

**Estimated win**: -60 % iteration count to reach the same business
outcome.

### 2. Prompt size dominates token cost; cache split is unused

**Evidence**: each rendered prompt is 13–14 K chars (~3.5 K input
tokens). The `<!-- CACHE -->` sentinel is in `_base.md` and the
`split_cacheable_prefix` helper exists, but the legacy CLI doesn't
route through `simulation.tools.llm_client.LlmClient`; cache hit count
across all batches was 0.

**Fix**: introduce an `--llm-client anthropic` flag on the CLI that, when
set, sends the rendered prompt through `LlmClient.complete()` with
`cache_control: ephemeral` on the prefix.

**Estimated win**: 50–80 % latency reduction on repeated prefix prompts.

### 3. `gh pr review --request-changes` fails on self-PRs

**Evidence**: every blocking verdict in this session degraded to
`--comment` by manual fallback. The fix is now in `review-pr.md` (PR
#139) but the loop's `merge_gate` selector still treats the
`--comment`-posted REVIEW-VERDICT as missing because it queries
`gh pr view --json reviews` instead of comments.

**Fix**: in
`simulation.tools.post_action_verify.verify_pr_merged` (and the
upstream `merge_gate` selector), broaden the review-source query to
include `gh pr view --json comments` and accept any comment containing
a `REVIEW-VERDICT:` from a known persona as a valid review.

**Estimated win**: removes the "phantom blocker" class of stall events.

## Repeated validation failures

In this 30-tick batch, **zero validations failed**. In the 50-tick
Cost-Tracking run, 8 / 50 failed — all of them on `merge_gate` and
`accept_pr` actions because those schemas were never written. Both
schemas were *not* added in this branch because the existing markers
(`RHEA-VERDICT:` for merge_gate, `ACCEPTANCE-DECISION:` for accept_pr)
*are* defined; the gap is only on the per-action `.schema.yaml`. Adding
the two schemas is a 10-minute fix.

## Long-running phases

| Phase | Avg ticks per module | Why |
|-------|----------------------|-----|
| design_solution | 1 (with diversity override) | Complex CoT (5 × 12 words) padding |
| implement_with_ac | 1 (chained) | AC enforcement requires extra section |
| review_pr | 1 (single reviewer) | Quorum at 1 for trivial helps; medium/complex still needs 2 |
| merge_gate | 1 | RHEA-VERDICT marker emit |
| close_issue + retrospective | 1 (chained close + lesson) | Lesson extraction LLM call (skipped in mock) |

## Recommended next code-fixes (ranked)

1. **Wire DedupeCache into `resolve_priority`** — single biggest perf
   win.
2. **Add `merge_gate.schema.yaml` and `accept_pr.schema.yaml`** —
   removes the only repeating validation failure class.
3. **Add `--llm-client` flag to the CLI** — unlocks prompt caching.
4. **Broaden review-source query to include comments** — closes the
   self-PR review-detection gap.
5. **Wire `enhance_prompt_with_lessons` into legacy CLI render** —
   activates lesson injection during real runs (currently 0 injected).

Once items 1, 2, and 5 land, a real 300-iteration run on this epic
should complete the remaining four modules + AC4/AC5/AC6 follow-ups
without diversity overrides and produce a fully-shipped PHP ERP core.
