# Dispatcher Architecture — how the autonomous loop never stops

**Status:** Accepted (user directive 2026-05-23)
**Replaces:** the earlier monolithic VS Code prompt that mixed dispatcher + decision logic.

---

## The shape

```
┌─────────────────────────────────────────────┐
│  Dispatcher (DUMB)                          │
│  - VS Code Claude Code session, OR          │
│  - the scheduled cloud routine, OR          │
│  - a bash `while true` calling next_prompt  │
│                                             │
│  while True:                                │
│      prompt = next_prompt.py --emit         │
│      launch_sub_agent(prompt)               │
│      # sub-agent does ONE iteration, exits  │
└─────────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│  simulation/tools/next_prompt.py (THE BRAIN)│
│                                             │
│  1. gather_state(repo)                      │
│     - gh pr list (status, mergeable, ...)   │
│     - gh pr view --comments per open PR     │
│     - gh issue list                         │
│     - .github/agent-prompts/ contents       │
│     - simulation/scenarios/ contents        │
│     - Epic #1 comments for retro/brainstorm │
│       timestamps                            │
│                                             │
│  2. resolve_next_action(state)              │
│     - Priority cascade (11 levels)          │
│     - NEVER returns None                    │
│     - Falls back to Ari triage if nothing   │
│       else fires                            │
│                                             │
│  3. render_prompt(action, repo)             │
│     - Per-action_type renderer              │
│     - Returns FULL self-contained prompt    │
│       (persona, task, steps, exit, caps)    │
└─────────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│  Sub-agent (independent, one-shot)          │
│  Reads the prompt. Acts. Exits.             │
│  Posts artifacts to GitHub.                 │
└─────────────────────────────────────────────┘
```

## Why this is correct

- **Single source of intelligence.** Change priority logic in one
  file (`next_prompt.py`), not in five different scheduled routines and
  VS Code prompts.
- **Dispatchers are interchangeable.** The same `next_prompt.py` is
  callable from the VS Code session, the cloud `RemoteTrigger`, a bash
  loop, or a CI job. None of them need to know the priority rules.
- **Sub-agents are stateless.** They get a complete prompt, act, exit.
  No long-lived state. Easy to scale, easy to retry on transient errors.
- **Never returns "nothing to do."** The cascade always has Echo /
  Nova / Meta-Sage / Ari fallbacks. If the loop ever exits unsolicited,
  that's a bug in `next_prompt.py`, not a planned state.

## Priority cascade (defined in `next_prompt.py:resolve_next_action`)

| # | Action type | Persona | Triggers when |
| --- | --- | --- | --- |
| 1 | `execute_merge` | Lina | All framework gates green on an open PR |
| 2 | `sim_human_approval` | Sim-Human Proxy | Rhea posted MERGE_READY, no Sim-Human approval yet |
| 3 | `merge_gate` | Rhea | All required reviewers in, Rhea hasn't decided |
| 4 | `review_pr` | (whichever) | A required reviewer is missing |
| 5 | `address_changes` | Lina | PR has CHANGES_REQUESTED |
| 6 | `migrate_persona` | Lina | No PR work pending; next persona in catalog |
| 7 | `implement_scenario` | Lina | No PR work pending; next scenario in catalog |
| 8 | `retrospective` | Echo | > 7 days since last Echo on Epic #1 |
| 9 | `brainstorm` | Nova | > 30 days since last Nova session |
| 10 | `meta_critique` | Meta-Sage | > 30 days since last Meta-Sage |
| 11 | `ari_triage` | Ari | Ultimate fallback — survey + propose 3 candidates |

## Usage from a dispatcher

### Bash loop (simplest)

```bash
while true; do
    python -m simulation.tools.next_prompt --emit > /tmp/next-prompt.md
    # launch your agent here, e.g.:
    # claude-code --prompt-file /tmp/next-prompt.md
    sleep 60
done
```

### From a script

```python
from simulation.tools.dispatcher import dispatch_once

prompt = dispatch_once("ci4me/ai-erp-foundation")
# now hand `prompt` to your agent runtime
```

### JSON form (for programmatic dispatchers)

```bash
python -m simulation.tools.next_prompt --emit-json
# emits {"action": {...}, "prompt": "..."}
```

### Probe only (no prompt, just status)

```bash
python -m simulation.tools.next_prompt --probe
# emits the resolved NextAction JSON — useful for monitoring without dispatching
```

## What sub-agents must do

Every sub-agent prompt emitted by `next_prompt.py` contains:

- **Who you are** (`persona_id`)
- **What action_type** you're executing
- **Target** (PR number, persona to migrate, etc.)
- **Cost cap** (per-iteration)
- **Exit criteria** (when you're done)
- **Why this action was picked** (rationale)
- **Step-by-step instructions** (action-type-specific)
- **The hard caps** (no `--admin` merge, no `--no-verify`, sign comments, exit cleanly)

The sub-agent must:

1. Read the prompt.
2. Execute the steps within the cost cap.
3. Post artifacts to GitHub (comments, commits, PRs, issues).
4. EXIT. Do not loop.

The dispatcher calls again.

## What this enables

- **The cloud routine** simplifies — its prompt becomes "call `python -m simulation.tools.next_prompt --emit` and execute the result". One brain, two dispatchers.
- **Composable cadences** — different dispatchers can call this on different schedules (every 4 h for the cloud routine, every 30 s for an interactive dev loop, every PR-merge for a webhook-triggered runner).
- **Single test surface** — to validate the loop logic, you test `resolve_next_action` against synthetic `FrameworkState` snapshots. No need to run real agents.
- **Inspectable decisions** — `--probe` shows what would be dispatched without spending tokens. Great for monitoring + debugging.

## What this prevents

- **Decision drift across dispatchers.** Old design: VS Code prompt + cloud routine prompt + bash scripts all had their own priority lists. Now: one file.
- **Stuck loops.** Old design: dispatcher could exit on "nothing to do" and not restart. Now: cascade always returns something; the only way out is human interruption.
- **Bypassed gates.** Old design: dispatcher could decide to `--admin` merge. Now: only the `execute_merge` action exists, and it explicitly forbids `--admin` and re-verifies state before merging.

## References

- [`simulation/tools/next_prompt.py`](../simulation/tools/next_prompt.py) — the brain
- [`simulation/tools/dispatcher.py`](../simulation/tools/dispatcher.py) — the trivial wrapper
- [`docs/amendment-policy.md`](./amendment-policy.md) — the gate rules that `review_pr` / `merge_gate` actions enforce
- [`docs/friction-budget.md`](./friction-budget.md) — the persona-activation matrix that `review_pr` reads from
