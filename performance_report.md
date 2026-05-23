# Performance Report — 45 real iterations

## 1. Overall statistics

- **Iterations executed**: 45 (target 45)
- **Avg latency (ms)**: 7208
- **Median latency (ms)**: 10341
- **p95 latency (ms)**: 11268
- **Total est. input tokens**: 204571
- **Total est. output tokens**: 33257
- **Posted GitHub artifacts**: 45
- **Validation pass rate**: 39/45 (87%)

## 2. Chaining

- **Iterations with chain length > 0**: 0
- **Average chain length**: 0.00
- **Round-trips saved by chaining**: 0
- _Note: chaining not exercised in this run (legacy CLI doesn't honor CHAIN-NEXT yet — see follow-up §5)._

## 3. CoT discipline

- **Avg CoT steps per body**: 5.7
- **Iterations with 5+ steps (complex)**: 45
- **Iterations with 3 steps (medium)**: 0
- **Iterations with <3 steps (trivial / off)**: 0

## 4. Diversity overrides

- **Iterations where the loop reselected an already-handled (action,persona,target) and was forced to rotate**: 37/45 (per batch summaries: 7 in A, 15 in B, 15 in C).
- **Root cause**: `next_prompt_legacy.resolve_priority` walks selectors first-match-wins with no per-tick history. Confirmed by Discussion #56.
- **Fix shipped (orchestrator layer)**: `next_prompt_orchestrator.DEDUPE_CACHE` + `STALL_TRACKER`. The legacy CLI does not yet consult them; the fix lives in `loop_runner.run_iterations` (PR #63). Wiring the legacy CLI to use them is the next step.

## 5. Bottlenecks observed

1. **Selector wedge dominates stalls.** Even with seeded sandbox issues #52–#71, the loop returned the same first-match selector hit every tick. Until `resolve_priority` consults the dedupe cache, the operator has to seed state between runs.
2. **`gh pr review --request-changes` refuses self-PR.** The template should auto-fallback to `--comment` when `pr.author == ci4me`.
3. **Validator schema gaps**. AUDIT-STATUS, DISCUSSION-STATUS, and a few orphan templates use the regex-fallback path. Long-term they should be promoted to first-class catalog actions.
4. **Prompt size**. Each rendered prompt is ~24k chars (~6k tokens). `<!-- CACHE -->` is set but the legacy CLI does not yet route through `llm_client.LlmClient`; cache hits are 0.

## 6. Top-3 follow-ups (ranked by impact)

1. **Wire `DEDUPE_CACHE` + `STALL_TRACKER` into `next_prompt_legacy.resolve_priority`** so the loop itself avoids the wedge — kills ~80% of overrides.
2. **Self-PR auto-fallback in `review-pr.md`** — eliminates the `gh pr review --request-changes` error path that downgrades every blocking verdict to a comment.
3. **Route the legacy CLI through `llm_client.LlmClient`** so the `<!-- CACHE -->` sentinel actually buys 50-80% latency savings on repeated ticks.

