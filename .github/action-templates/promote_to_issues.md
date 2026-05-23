---
id: promote-to-issues
description: Promote a resolved plan into milestone + issues + project card
---

# Promote Plan to Issues

Run after `facilitate_planning` posted `PLAN-READY: POSTED` on a
Discussion. Convert the `PLAN-SUMMARY:` block into GitHub artifacts.

## Steps

1. **Create the milestone** (only if the plan has more than one issue):

   ```bash
   gh api repos/{{repo}}/milestones \
     -f title="{{plan_title}}" \
     -f description="{{plan_summary_text}}"
   ```

2. **Create issues** using `.github/ISSUE_TEMPLATE/plan.md`:
   - Title: `[PLAN] <subtask>`.
   - Body includes `PLAN-STATUS: DRAFT`, the AC checklist
     (`- [ ] AC1: …`), and a `TEST-STRATEGY:` section.
   - Label `plan`.

3. **(Optional) Attach to the Project board** named `Planning Board`:

   ```bash
   gh project item-add <project-number> --content-id <issue-id>
   ```

4. **Post the summary back on the discussion** so future ticks see the
   link:

   ```
   PROMOTION-COMPLETE: POSTED milestone="{{plan_title}}" issues=[#a,#b,#c]
   ```

## Output marker

```
PROMOTION-COMPLETE: POSTED
```
