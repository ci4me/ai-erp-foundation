# `simulation/scorecards/` — per-persona performance scorecards

(Phase 2.) After every live-mode regression run, the orchestrator writes a
JSON scorecard here for each persona. Fields (per Prism's spec from
[Discussion #2 comment-17026083](https://github.com/ci4me/ai-erp-foundation/discussions/2#discussioncomment-17026083)):

```json
{
  "persona_id": "theo-architect",
  "last_run": "2026-05-22T22:11:43Z",
  "model": "claude-opus-4-7-1m",
  "scenarios": {
    "001-suspend-cookie": {
      "verdict_matched": true,
      "flaws_must_catch": ["F1", "F2", "F7"],
      "flaws_caught": ["F1", "F2", "F7", "F4"],
      "flaws_missed": [],
      "hallucinations": 0,
      "tokens_in": 12450,
      "tokens_out": 1820,
      "cost_usd": 0.32
    }
  },
  "aggregate": {
    "fp_rate": 0.05,
    "fn_rate": 0.02,
    "avg_tokens_per_run": 14270,
    "avg_cost_usd": 0.32,
    "sim_pass_rate": 1.0
  }
}
```

Scorecards are read by:

- **`run.py`** — to detect drift (FP/FN rate change > threshold = warning).
- **Cora (Cost Architect)** — to compute monthly cost projections (Theme C).
- **Prism (PromptOps)** — to identify personas due for prompt revision (Theme B).

Until live mode lands, this directory ships empty (other than this README).
