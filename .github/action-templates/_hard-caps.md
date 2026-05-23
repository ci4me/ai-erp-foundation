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
- **Prompt caching**: the rendered prompt prefix is delimited by `<!-- CACHE -->` so SDK callers can mark everything above it as `cache_control: ephemeral`. Do not move the sentinel.

## Marker discipline (NON-NEGOTIABLE)

- **Never post a comment, review, or discussion reply without a marker.** The autonomous loop's selectors and `simulation.tools.validator` are blind to prose-only output; an un-markered comment is treated as "no signal".
- Use the marker declared by the action schema in `.github/action-templates/schemas/<action>.schema.yaml` when one applies.
- If you are unsure which marker is correct, end your output with `CLARIFICATION-REQUEST: POSTED` and ask in the body — that surfaces the ambiguity instead of dropping it.
- Issues/PRs/discussions arrive un-markered when humans open them by hand. The `scripts/inject_markers_everywhere.sh` one-shot repair walks the repo and adds default markers (`TEAM-REQUEST:`, `REVIEW-REQUEST:`, `PLAN-REQUEST:`); run it after a fresh fork or after a long human-only stretch.

## Action Chaining Limits

- Max chain length: 3 actions per iteration.
- To chain, end your output with `CHAIN-NEXT: <action_id>` on its own line.
- The chained action runs immediately, using the same in-memory issue object — no fresh GitHub fetch between chain steps. You can chain `implement_issue` → `review_pr` → `merge_pr` → `close_issue` in a single iteration.
- Validation runs on every chained action; if any chained action fails validation, the chain breaks and the iteration ends.
- Only chain actions in `simulation.tools.loop_speedup.ALLOWED_CHAIN_ACTIONS` (review_pr, merge_gate, accept_pr, merge_pr, close_issue, address_changes_requested, consistency_check, open_followup_issue, request_clarification).
- Do not chain actions that depend on human input or external state that has not been updated yet (for example, triage_issue or design_solution should not be chained after implement_issue without a fresh state read).

