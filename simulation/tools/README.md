# `simulation/tools/` — meta-tools for the framework

These scripts operate ON the framework, not WITH it. They snapshot, analyze,
critique, and generate prompts for the AI-agents-on-GitHub system itself.
Built in response to the directive "be creative — much more advanced
tooling."

## Catalog

| Script | What it does | Output | Notes |
| --- | --- | --- | --- |
| [`next_prompt.py`](./next_prompt.py) | Reads live repo state, identifies the next priority work item, generates the exact self-contained autonomous-loop prompt | Markdown to stdout (or `--output FILE`) | The headliner. Pipe to a remote agent or paste into Claude/Grok/GPT. |
| [`coverage_matrix.py`](./coverage_matrix.py) | Aggregates `simulation/scorecards/*.json` into a persona × scenario matrix; identifies dead personas + flaw-detection MVPs | Markdown table + JSON | Drives Cora's redundancy audit with real data instead of projections. |
| [`arch_snapshot.py`](./arch_snapshot.py) | Captures full GitHub repo state (PRs, issues, discussions, milestones, labels, persona files, scenarios) into a JSON snapshot; diffs against a previous snapshot to show framework evolution | JSON snapshot + Markdown diff | Single-pane view. Run weekly via cron for a framework-velocity dashboard. |
| [`meta_sage.py`](./meta_sage.py) | Self-critique persona. Reads operating model + persona prompts + recent activity, dispatches Claude with a brutal-honesty system prompt, produces critique Markdown | Markdown to stdout | The framework reviewing itself. Run after major changes. |

## Usage patterns

### "What should the next agent do?"

```bash
python -m simulation.tools.next_prompt --repo ci4me/ai-erp-foundation
```

Outputs the priority-resolved prompt. Pipe it to a remote agent, paste it
into a chat, or feed it to `RemoteTrigger`.

### "Which personas earn their keep?"

```bash
python -m simulation.tools.coverage_matrix
```

Reads every scorecard. Reports per-persona unique-flaw-catch rate. Personas
below threshold (e.g., 0 unique catches across all scenarios) are candidates
for Cora's demote-to-observer list.

### "What changed in the framework this week?"

```bash
python -m simulation.tools.arch_snapshot --output snapshot-$(date +%Y%m%d).json
python -m simulation.tools.arch_snapshot --diff snapshot-prev.json snapshot-$(date +%Y%m%d).json
```

### "Where are the framework's blind spots?"

```bash
ANTHROPIC_API_KEY=sk-... python -m simulation.tools.meta_sage
```

Costs ~$0.50–$2 per run depending on context size.

## Adding a new meta-tool

1. Add a script under `simulation/tools/<name>.py` with a self-contained `main()`.
2. Document its purpose in the table above.
3. If it calls Anthropic, gate behind `ANTHROPIC_API_KEY` like `meta_sage`.
4. Open a sub-issue under #1 (Epic E01) so the catalog stays GitHub-visible.

## Design constraints

- **No production-side effects.** These tools READ repo state and write
  *new* artifacts (snapshots, reports). They never push commits or open
  PRs. Workflow scripts do that.
- **Standalone CLIs.** Each tool has a `__main__` block and works without
  imports from elsewhere in `simulation/`. The exception is `next_prompt.py`,
  which reads persona files to discover what exists.
- **Graceful when empty.** If scorecards / snapshots / personas haven't
  been generated yet, tools degrade to "no data yet" instead of erroring.
