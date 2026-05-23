---
id: hard-caps
description: Non-negotiable autonomous-loop limits shared by every action
---

## Hard Caps (NON-NEGOTIABLE)

- Max 3 file writes per iteration.
- Max 2 sub-agent dispatches.
- Max 6 Bash calls.
- Per-iteration budget ceiling: $5.00.
- Never bypass commit hooks (`--no-verify`, `SKIP_TESTS=1`).
- Never run destructive git ops (`rm -rf`, `push --force`).
- Sign every GitHub comment with the v0.3 YAML persona header: `Persona`, `Role`, `Layer`, `Model`, `Source`, `Self-review conflict`, `Run-ID`.
- Every commit ends with a `Co-Authored-By:` trailer naming your model.
- Post an end-of-run summary as a comment on Epic #1.
- After posting the summary, do not guess the next task. The next task is produced by rerunning `next_prompt.py`.
- Never continue a discussion/comment thread after a terminal lifecycle marker (`DISCUSSION-STATE: RESOLVED|PROMOTED|DEFERRED|CLOSED`, `ISSUE-STATE: CLOSED`, `ACCEPTANCE-DECISION: REJECT`) unless a newer explicit `NEEDS-*` marker reopens work.
- Never post a duplicate persona response unless `next_prompt.py` selected that persona from fresh GitHub state.
- Never post a PR review, discussion comment, acceptance decision, or close decision without passing `python -m simulation.tools.validate_agent_action` for the body you are about to post.
- Never convert a discussion/comment into an Issue unless the selected action is `create_issue` or `promote_idea` and the source contains `CREATE-ISSUE:` or `PROMOTE-TO-ISSUE:`.
- **Action chaining**: an output may end with `CHAIN-NEXT: <action>` to skip the next round-trip and continue inline. The chain depth is capped at 3 actions per iteration. Allowed chain targets are listed in `simulation/tools/loop_speedup.ALLOWED_CHAIN_ACTIONS`. After 3 chained actions, stop and let `next_prompt.py` re-read fresh GitHub state.
- **Prompt caching**: the rendered prompt prefix is delimited by `<!-- CACHE -->` so SDK callers can mark everything above it as `cache_control: ephemeral`. Do not move the sentinel.

