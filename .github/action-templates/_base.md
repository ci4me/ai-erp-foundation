---
id: base
description: Wrapper around every autonomous-loop action prompt
---

# Autonomous loop - next iteration ({{priority}})

Generated at {{generated_at}} by `simulation/tools/next_prompt.py`.

This prompt is built from live GitHub state for `{{repo}}` plus repository-owned files:

- Action template: `{{template_path}}`
- Persona prompts: `.github/agent-prompts/*.md`
- Common hard caps: `.github/action-templates/_hard-caps.md`

The goal is mechanical execution. Follow the numbered steps in order. When you finish, stop and let the next session run `python3 -m simulation.tools.next_prompt --repo {{repo}}` again so the loop re-reads the new GitHub state.

{{hard_caps}}

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
