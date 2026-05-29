# Design: next_prompt rendering cache

> Status: Proposal
> Owner persona: theo-architect
> Source: issue #52 (`sandbox: discuss caching strategy for next_prompt rendering`)
> Acceptance criterion satisfied: this document offers at least two options and a recommendation.

## Problem

Each `python3 -m simulation.tools.next_prompt` invocation renders ~50k chars of
prompt context, including:

1. The full action catalog summary (read from `.github/action-templates/catalog.yml` and per-action template headers).
2. The persona index (read from `.github/agent-prompts/*.md` frontmatter).
3. Live GitHub state (issues, PRs, discussions, comments).

Items 1 and 2 change at most a few times per sprint. Item 3 changes every tick.
Today we re-read items 1 and 2 from disk on every call, even when nothing in
`.github/` has changed since the previous tick. On a 30-tick batch this is
~30 redundant filesystem walks and ~30 redundant YAML parses.

## Goals

- Cut per-tick prompt-rendering wall time by >= 40% on a hot cache.
- Preserve full correctness when any file under `.github/action-templates/`,
  `.github/agent-prompts/`, or `.github/action-templates/schemas/` changes.
- Stay deterministic enough for replay: a given commit + GitHub state must
  always render the same prompt regardless of cache state.
- No new runtime dependencies.

## Option A — In-process LRU keyed by source-tree mtime

A single `functools.lru_cache(maxsize=8)` on the catalog loader and persona
loader, keyed by the max `mtime` across the relevant source trees.

- **Pros:** zero new files, no cross-process state, trivial to revert, easy to
  test (cache hits are observable via lru_cache info).
- **Cons:** every fresh Python process re-pays the cold-start cost. The loop
  is invoked from new subprocesses today, so the hit rate would be zero on
  the current operator flow.
- **Eligibility:** correct only when next_prompt is invoked as a long-running
  daemon (e.g. routine mode); not useful for one-shot CLI use.

## Option B — On-disk fingerprint cache under `simulation/_cache/`

A small append-only JSON cache at `simulation/_cache/next_prompt_render.json`
that maps `(sha256 of relevant tree, action_id) -> rendered fragment`. Cache
keys are tree hashes; cache values are the rendered substrings.

- **Pros:** survives subprocess boundaries; first-tick warm-up cost amortises
  across the entire batch; deterministic (key is content hash).
- **Cons:** new file under `simulation/` requires `.gitignore` discipline so
  the cache does not pollute commits; reads must be locked under concurrent
  ticks; cache invalidation is one bug class we did not have before.
- **Eligibility:** correct for both one-shot and routine modes.

## Recommendation

Adopt **Option B** with a strict scope guard: cache only the *static* parts of
the prompt (action catalog summary + persona index + action template body).
Never cache the GitHub-state section. This keeps replay determinism intact and
cuts redundant disk walks to one per tree-hash change.

Implementation outline:

1. Add `simulation/tools/_render_cache.py` exposing `get(tree_hash, action_id)`
   and `put(tree_hash, action_id, fragment)`, backed by
   `simulation/_cache/next_prompt_render.json`.
2. Add `simulation/_cache/` to `.gitignore`.
3. Wire `next_prompt_legacy.py:render_prompt` to consult the cache for items 1
   and 2 only.
4. Add a unit test that mutates `.github/agent-prompts/lina-implementer.md`
   between two `render_prompt` calls and asserts the cache key changes.
5. Cap the cache at 50 entries (LRU eviction) so the file stays under ~5 MB.

## Out of scope

- Caching the rendered GitHub-state section.
- Cross-machine cache sharing.
- Pre-warming the cache from CI.

## Rollback

Delete `simulation/_cache/` and revert the import in `next_prompt_legacy.py`.
The on-disk cache file is the only artifact.

## Acceptance criteria recheck

- [x] At least two options described (A: in-process LRU; B: on-disk fingerprint cache).
- [x] A recommendation is stated (B, with scope guard).
- [x] Owner persona named (theo-architect).
- [x] Source evidence linked (issue #52).

Closes #52.
