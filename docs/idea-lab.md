# Idea Lab — brainstorm surface for `ci4me/ai-erp-foundation`

**Status:** Accepted (closes the "no brainstorm surface" gap, 2026-05-23)
**Owner:** Nova (Idea Generator) + Mara (Product Owner, promotion authority)
**GitHub primitive:** Discussion category (NOT Issue template)

---

## Why Discussions, not Issues

Issues imply work. Discussions imply debate. Brainstorm ideas need to be
debatable, threaded, reaction-counted, and **mostly killed** without
becoming closed issues that clutter the backlog.

- Discussions support 👍/👎/🚀 reactions natively — the upvote signal is
  the promotion gate.
- Discussions can be marked "answered" — the promotion event.
- Discussions don't show up in `gh issue list` — keep noise out of the
  work queue until promoted.

## How an idea flows

```text
Nova session fires (monthly cron or workflow_dispatch)
  ↓
Nova posts 5 Discussion threads in "Idea Lab" category
  (hard cap: 5/session, every idea carries a kill criterion)
  ↓
Humans react in the next 14 days
  ↓
  ├─ ≥ 3 distinct human reactions → auto-labeled `idea:promotable`
  │       ↓
  │   Mara runs `/promote-idea <discussion-url>`
  │       ↓
  │   Workflow converts Discussion → `feature.yml` Issue with owner
  │       ↓
  │   Issue enters the normal Phase-0 work queue
  │
  ├─ < 3 reactions within 14 days → auto-closed with label `idea:didnt-stick`
  │       ↓
  │   Echo reads quarterly, tunes Nova's prompt
  │
  └─ Maintainer reacts 👎 → auto-labeled `idea:rejected`, immediate close
```

## Anti-spam guards

1. **Nova caps at 5 ideas per session.** Hardcoded in `nova-idea-generator.md`.
2. **One thread = one idea.** No mega-threads.
3. **Bot/Nova reactions don't count** toward the 3-reaction promotion gate (filtered by maintainer-list membership).
4. **Cost ceiling:** $2 per Nova session via `--max-cost-usd $2`; monthly
   Idea Lab spend ceiling $10 in `.github/workflows/idea-lab.yml`. Cora
   enforces.
5. **30-day TTL:** any thread with no movement gets auto-closed with
   `idea:didnt-stick`. Echo tunes Nova based on cumulative didnt-stick
   pattern.

## Promotion mechanics

The `/promote-idea <discussion-url>` slash command is a `workflow_dispatch`
trigger (defined in `.github/workflows/idea-lab.yml`) that:

1. Reads the Discussion body.
2. Creates a new Issue via `.github/ISSUE_TEMPLATE/feature.yml` (TBD)
   pre-filled with: title (from Discussion), body (from Discussion +
   kill criterion), assigned to CODEOWNER for the touched area, labeled
   `work:feature` + `risk:medium` + `area:*` based on Mara's input.
3. Comments on the Discussion: "Promoted to Issue #N — closing thread."
4. Closes the Discussion as "answered".

Only Mara can invoke `/promote-idea` — the workflow checks the actor's
membership in the `product-owners` GitHub team. (Until per-persona Apps
land, that's `@ci4me` plus future Mara-bot identities.)

## Where the human plugs in

**Mara is the sole promotion authority.** She decides which `idea:promotable`
threads become Issues. Maintainers' reactions count toward the 3-reaction
gate; bot/Nova reactions don't.

## Cadence

- Cron: monthly, 1st of month at 09:00 UTC.
- Manual: `gh workflow run idea-lab.yml` for ad-hoc bursts.

## References

- Persona: [`.github/agent-prompts/nova-idea-generator.md`](../.github/agent-prompts/nova-idea-generator.md)
- Workflow: [`.github/workflows/idea-lab.yml`](../.github/workflows/idea-lab.yml)
- Promotion target: `.github/ISSUE_TEMPLATE/feature.yml` (Phase-1 sub-issue)
- Cost ceiling integration: `cost-telemetry.yml` (Theme C, Cora)
