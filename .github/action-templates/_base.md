---
id: base
description: Wrapper around every autonomous-loop action prompt
---

<!-- CACHE -->
# Autonomous loop - next iteration ({{priority}})

Generated at {{generated_at}} by `simulation/tools/next_prompt.py`.

This prompt is built from live GitHub state for `{{repo}}` plus repository-owned files:

- Action template: `{{template_path}}`
- Persona prompts: `.github/agent-prompts/*.md`
- Common hard caps: `.github/action-templates/_hard-caps.md`

The goal is mechanical execution. Follow the numbered steps in order. When you finish, stop and let the next session run `python3 -m simulation.tools.next_prompt --repo {{repo}}` again so the loop re-reads the new GitHub state.

{{hard_caps}}

## Chain of Thought (REQUIRED — length depends on task complexity)

Before writing your final output, produce a numbered ``**Reasoning:**``
block. The minimum length is set by task complexity — the renderer fills in
the actual numbers via the variables below:

- **Trivial tasks** (label ``trivial`` or quick fix): at least 2 steps,
  5 words each.
- **Medium tasks** (default): at least 3 steps, 8 words each.
- **Complex tasks** (label ``complex``, ``risk:high``, ``risk:critical`` or
  keywords like *architecture*, *database*, *api*, *security*): at least
  5 steps, 12 words each.

### Step template (pick the ones that apply)

1. **Restate the goal** — what must be achieved?
2. **Review context** — constraints, previous decisions, current state.
3. **List alternatives** — at least 2 possible approaches (if applicable).
4. **Plan the work** — break down what you will output.
5. **Risks & mitigation** — what could go wrong and how to avoid it.
6. **Dependencies** — external libraries or changes elsewhere.
7. **Testing strategy** — how will you verify correctness?

### Output format

```
**Reasoning:**
1. [step 1]
2. [step 2]
...

<your normal output here, ending with the required marker>
```

Do **not** repeat the issue body inside reasoning steps — refer to it by
identifier or section name.

## Token-discipline rules (NON-NEGOTIABLE)

- **Do not quote or repeat** the issue title, description, or earlier comments
  unless explicitly asked. Focus your output on new content only.
- Before replying, **read the decision log** at the bottom of the issue body
  (`<!-- DECISIONS: ... -->`). Never contradict an accepted decision; if you
  must, emit `REOPEN-DECISION: <key>` first and stop.
- If this is a follow-up to a previous design or implementation, **output only
  the delta**: added sections, modified lines, removed items. Do not re-emit
  the unchanged parts.
- For PR diffs larger than 200 lines, **do not request the full diff**. Read
  the file list first (`gh pr view --json files`), pick the suspicious files,
  and read only those.

## Posting Mode

This prompt was rendered with `post_mode={{post_mode}}`.

- If `post_mode=real`, run the posting commands after validation passes.
- If `post_mode=dry-run`, do not mutate GitHub. Render files, run validation, and print the command that would have posted.

## Current Repository State

- Open PRs: {{open_pr_count}}
- Open issues: {{open_issue_count}}
- Open discussions: {{open_discussion_count}}
- Open milestones: {{open_milestone_count}}
- PRs with `CHANGES_REQUESTED`: {{changes_requested_count}}
- Existing persona prompts: {{existing_personas}}
- Missing persona prompts: {{missing_personas}}
- Existing scenarios: {{existing_scenarios}}
- Missing scenarios / scorecards: {{scenarios_without_scorecards}}

### Open PRs

{{open_prs_table}}

### Open Discussions

{{open_discussions_table}}

### Open Milestones

{{open_milestones_table}}

### Full Action Catalog

This catalog is shown so the impersonated persona knows its other legal moves, but the selected action for this iteration is still `{{priority}}`.

{{action_catalog_summary}}

{{action_prompt}}
