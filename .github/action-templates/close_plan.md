---
id: close-plan
description: Close a plan milestone and emit release notes
---

# Close Plan

Final step after every issue in a plan milestone is closed. Closes the
milestone, posts release notes, and stores a retrospective lesson.

## Steps

1. **Close the milestone**:

   ```bash
   gh api repos/{{repo}}/milestones/{{milestone_number}} \
     -X PATCH -f state=closed
   ```

2. **Move the project card** (if a Planning Board project exists) to
   `Done`.

3. **Generate release notes** — one bullet per issue closed in this
   milestone with the linked PR URL.

4. **Store a retrospective lesson** via
   `simulation.tools.retrospective.Retrospective.process_closed_issue`
   so the loop learns from this plan.

## Required output marker

```
RELEASE-NOTES: POSTED
PLAN-STATUS: DONE
```
