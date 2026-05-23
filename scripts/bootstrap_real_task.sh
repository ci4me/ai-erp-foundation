#!/usr/bin/env bash
# bootstrap_real_task.sh
#
# Cold-start helper: open one trivial issue with the markers the loop
# needs, then render the first prompt so an operator can hand it to an
# agent and observe the full implement → review → merge → close cycle.
#
# Usage:
#     bash scripts/bootstrap_real_task.sh
#     REPO=other-org/repo bash scripts/bootstrap_real_task.sh
#
# The script intentionally creates *one* small piece of work so the
# loop's chaining + auto-approval rules can be exercised end-to-end on
# a single iteration. Pair with:
#     python3 -m simulation.tools.next_prompt --post-mode real --max-iterations 1
# to see the loop pick the issue up.

set -euo pipefail

REPO="${REPO:-ci4me/ai-erp-foundation}"

# Ensure labels exist (idempotent).
gh label create trivial --color c2e0c6 --description "Trivial fix; bypass triage and design" --repo "$REPO" 2>/dev/null || true
gh label create ready-for-agent --color 0e8a16 --description "Marker-tagged for next loop iteration" --repo "$REPO" 2>/dev/null || true

ISSUE_URL=$(gh issue create --repo "$REPO" \
    --title "bootstrap: fix typo 'teh' → 'the' in README.md" \
    --body "TEAM-REQUEST: There is a typo in README.md line 12: 'teh' should be 'the'. This is a one-character fix.

## Acceptance Criteria
- [ ] AC1: Change 'teh' to 'the' on README.md line 12
- [ ] AC2: No other lines touched
- [ ] AC3: Spelling check shows no remaining typos

The autonomous loop should:
1. Pick this up because of \`TEAM-REQUEST:\` and the \`ready-for-agent\` label.
2. Hit the \`quick_fix_bypass\` → skip triage + design.
3. Open a PR via \`implement_issue\`.
4. Auto-approve via the trivial-PR rule in review-pr.md.
5. Merge and close in one chained iteration." \
    --label trivial,ready-for-agent)

echo "✅ Created issue: $ISSUE_URL"
echo ""
echo "Now run the loop:"
echo "    python3 -m simulation.tools.next_prompt --post-mode real --max-iterations 1"
echo ""
echo "Expected outcome: a PR opened on a 'fix/teh-typo' branch, auto-approved,"
echo "merged, and the bootstrap issue closed within one chained iteration."
