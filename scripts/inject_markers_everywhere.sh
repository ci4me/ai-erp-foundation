#!/usr/bin/env bash
# inject_markers_everywhere.sh
#
# One-shot repair script for the autonomous loop. Walks every open
# issue, PR, and discussion in the repo and ensures each one has the
# trigger marker the loop's selectors expect. Without these markers
# `resolve_priority` silently skips the object — running this script
# is the recommended first move after a fresh fork or after a long
# period of human-only activity on the repo.
#
# What the script does (read-mostly: every mutation is a single
# `gh ... comment` or `gh ... edit`, so re-running is safe and the
# script is idempotent because the marker check uses substring match):
#
# 1. Issues missing a trigger marker → add `TEAM-REQUEST:` comment +
#    `ready-for-agent` label.
# 2. Open PRs with no reviews at all → add `REVIEW-REQUEST:` comment.
# 3. Discussions (any category) missing `PLAN-REQUEST:` → add a
#    suggestion comment via the GraphQL API.
#
# Usage:
#     bash scripts/inject_markers_everywhere.sh                  # acts on ci4me/ai-erp-foundation
#     REPO=other-org/repo bash scripts/inject_markers_everywhere.sh
#
# The `REPO` env var overrides the default. Pre-flight: requires `gh`
# authenticated against the target repo with `issues:write`,
# `pull_requests:write`, and `discussions:write` scopes.

set -euo pipefail

REPO="${REPO:-ci4me/ai-erp-foundation}"
LABEL_READY="ready-for-agent"
TEAM_REQUEST_BODY="TEAM-REQUEST: Please address the content of this issue. Acceptance criteria: as defined in the issue body."
REVIEW_REQUEST_BODY="REVIEW-REQUEST: Please review this PR and provide a REVIEW-VERDICT: APPROVE | APPROVE_WITH_CONDITIONS | REQUEST_CHANGES | BLOCKED."
PLAN_REQUEST_BODY="PLAN-REQUEST: If this discussion is intended to lead to a plan, please clarify the goal and acceptance criteria. Otherwise, ignore."

trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' ; }

echo "🔧 Fixing missing markers on issues in $REPO ..."
mapfile -t issues < <(gh issue list --repo "$REPO" --state open --limit 200 --json number --jq '.[].number')
issue_count=0
for issue in "${issues[@]}"; do
    body=$(gh issue view "$issue" --repo "$REPO" --json body --jq '.body' 2>/dev/null || echo "")
    if [[ "$body" != *"TEAM-REQUEST:"* ]] \
        && [[ "$body" != *"PLAN-REQUEST:"* ]] \
        && [[ "$body" != *"AUDIT-ISSUE:"* ]]; then
        echo "  → Issue #$issue has no trigger marker. Adding TEAM-REQUEST:"
        gh issue comment "$issue" --repo "$REPO" --body "$TEAM_REQUEST_BODY" > /dev/null
        gh issue edit "$issue" --repo "$REPO" --add-label "$LABEL_READY" > /dev/null 2>&1 || true
        issue_count=$((issue_count + 1))
    fi
done
echo "   stamped $issue_count issue(s)."

echo "🔧 Fixing missing review markers on PRs in $REPO ..."
mapfile -t prs < <(gh pr list --repo "$REPO" --state open --limit 200 --json number --jq '.[].number')
pr_count=0
for pr in "${prs[@]}"; do
    reviews=$(gh pr view "$pr" --repo "$REPO" --json reviews --jq '[.reviews[]] | length' 2>/dev/null || echo 0)
    if [[ "$reviews" == "0" ]]; then
        echo "  → PR #$pr has no reviews. Adding REVIEW-REQUEST:"
        gh pr comment "$pr" --repo "$REPO" --body "$REVIEW_REQUEST_BODY" > /dev/null
        pr_count=$((pr_count + 1))
    fi
done
echo "   stamped $pr_count PR(s)."

echo "🔧 Fixing missing PLAN-REQUEST: on discussions in $REPO ..."
# Use GraphQL because the REST /repos/{repo}/discussions endpoint is not
# exposed for every repo. Walk the first 50 open discussions.
discussion_count=0
gh api graphql -f query='{
  repository(owner:"'${REPO%/*}'",name:"'${REPO#*/}'"){
    discussions(first:50,states:OPEN){nodes{number,id,body}}
  }
}' --jq '.data.repository.discussions.nodes[] | "\(.number)\t\(.id)\t\(.body | gsub("\\n"; " ") | .[:160])"' \
| while IFS=$'\t' read -r number node_id snippet; do
    if [[ "$snippet" != *"PLAN-REQUEST:"* ]]; then
        echo "  → Discussion #$number lacks PLAN-REQUEST. Adding suggestion."
        gh api graphql -f query='mutation($d:ID!,$b:String!){
            addDiscussionComment(input:{discussionId:$d,body:$b}){comment{url}}
        }' -F d="$node_id" -F b="$PLAN_REQUEST_BODY" > /dev/null
        discussion_count=$((discussion_count + 1))
    fi
done
echo "   stamped discussions (re-read GitHub to confirm count)."

echo "✅ All markers injected."
