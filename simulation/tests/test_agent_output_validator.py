from simulation.tools import agent_event_guard, agent_output_validator


VALID_REVIEW = """---
Persona: Iris
Role: AI Security Reviewer
Layer: assurance
Model: claude-sonnet-4-6
Source: PR #35 diff
Self-review conflict: Yes
Run-ID: 2026-05-23T05:00:00Z-iris-review
---

REVIEW-VERDICT: APPROVE_WITH_CONDITIONS

**Verdict:** APPROVE_WITH_CONDITIONS

**Security summary:** The workflow has bounded permissions but needs clearer budget enforcement.

**Acceptance matrix:**
| Criterion | Status | Evidence (path:line or MISSING) |
| --- | --- | --- |
| Workflow permissions are minimal | PASS | .github/workflows/idea-lab.yml:31 |

**Blocking findings:**
1. none

**Non-blocking findings:**
1. Clarify budget enforcement in docs/idea-lab.md:45.

**Required next action:** Run next_prompt.py again after posting.
"""


VALID_DISCUSSION_COMMENT = """---
Persona: Mara
Role: AI Product Owner
Layer: executive
Model: claude-sonnet-4-6
Source: Discussion #12 body + comments
Self-review conflict: No
Run-ID: 2026-05-23T05:00:00Z-discussion-12
---

## Discussion response

DISCUSSION-STATE: OPEN

**Verdict:** PROMOTE

**Reasoning:** The idea has clear user value and a small implementation slice.

**Required next action:** Open a feature issue with acceptance criteria.
"""


VALID_CLOSE_DISCUSSION = """---
Persona: Mara
Role: AI Product Owner
Layer: executive
Model: claude-sonnet-4-6
Source: Discussion #12 body + comments
Self-review conflict: No
Run-ID: 2026-05-23T05:00:00Z-close-discussion-12
---

DISCUSSION-STATE: PROMOTED

**Reason:** Promoted to Issue #44 after meeting the reaction gate.
"""


VALID_REVIEW_REQUEST = """---
Persona: Ari
Role: AI Orchestrator
Layer: executive
Model: claude-sonnet-4-6
Source: PR #35 review state
Self-review conflict: No
Run-ID: 2026-05-23T05:00:00Z-request-review-35
---

REVIEW-REQUEST: iris-security

**Reason:** PR touches `.github/workflows/**`, so Iris must review workflow permissions.
"""


VALID_ACCEPT = """---
Persona: Rhea
Role: AI Release Manager
Layer: assurance
Model: claude-sonnet-4-6
Source: PR #35 reviews + CI
Self-review conflict: No
Run-ID: 2026-05-23T05:00:00Z-accept-pr-35
---

ACCEPTANCE-DECISION: ACCEPT

**Evidence:** Required persona reviews are present and CI is green.
"""


def test_valid_review_pr_output_passes():
    result = agent_output_validator.validate_agent_output(
        VALID_REVIEW,
        persona_id="iris-security",
        action="review_pr",
    )

    assert result.valid
    assert result.verdict == "APPROVE_WITH_CONDITIONS"


def test_missing_header_fails():
    result = agent_output_validator.validate_agent_output("**Verdict:** APPROVE", persona_id="iris-security")

    assert not result.valid
    assert "missing leading YAML persona header" in result.errors


def test_invalid_verdict_for_persona_fails():
    body = VALID_REVIEW.replace("APPROVE_WITH_CONDITIONS", "MERGE_READY")

    result = agent_output_validator.validate_agent_output(body, persona_id="iris-security", action="review_pr")

    assert not result.valid
    assert any("not allowed" in error for error in result.errors)


def test_unresolved_placeholder_fails():
    body = VALID_REVIEW + "\nCHANGE_ME\n"

    result = agent_output_validator.validate_agent_output(body, persona_id="iris-security", action="review_pr")

    assert not result.valid
    assert any("unresolved placeholder" in error for error in result.errors)


def test_review_pr_requires_template_sections():
    body = VALID_REVIEW.replace("**Acceptance matrix:**", "**Notes:**")

    result = agent_output_validator.validate_agent_output(body, persona_id="iris-security", action="review_pr")

    assert not result.valid
    assert any("acceptance matrix" in error for error in result.errors)


def test_comment_discussion_output_passes():
    result = agent_output_validator.validate_agent_output(
        VALID_DISCUSSION_COMMENT,
        persona_id="mara-product-owner",
        action="comment_discussion",
    )

    assert result.valid
    assert result.verdict == "PROMOTE"


def test_close_discussion_requires_terminal_marker():
    result = agent_output_validator.validate_agent_output(
        VALID_CLOSE_DISCUSSION,
        persona_id="mara-product-owner",
        action="close_discussion",
    )

    assert result.valid


def test_request_review_marker_passes():
    result = agent_output_validator.validate_agent_output(
        VALID_REVIEW_REQUEST,
        persona_id="ari-orchestrator",
        action="request_review",
    )

    assert result.valid


def test_accept_pr_marker_passes():
    result = agent_output_validator.validate_agent_output(
        VALID_ACCEPT,
        persona_id="rhea-release-manager",
        action="accept_pr",
    )

    assert result.valid


def test_infer_action_from_markers():
    assert agent_output_validator.infer_action(VALID_ACCEPT) == "accept_pr"
    assert agent_output_validator.infer_action(VALID_CLOSE_DISCUSSION) == "close_discussion"
    assert agent_output_validator.infer_action(VALID_REVIEW_REQUEST) == "request_review"


def test_event_guard_skips_human_comment():
    event = {"comment": {"body": "LGTM"}, "issue": {}}

    assert agent_event_guard.validate_event(event, event_name="issue_comment") is None


def test_event_guard_validates_pr_issue_comment():
    event = {
        "comment": {"body": VALID_REVIEW},
        "issue": {"pull_request": {"url": "https://api.github.test/pulls/35"}},
    }

    result = agent_event_guard.validate_event(event, event_name="issue_comment")

    assert result is not None
    assert result.valid
    assert result.action == "review_pr"


def test_discussion_state_open_infers_comment_discussion_not_close():
    body = """---
Persona: Mara
Role: AI Product Owner
Layer: executive
Model: claude-sonnet-4-6
Source: Discussion #12
Self-review conflict: No
Run-ID: 2026-05-23T05:00:00Z-discussion-open
---

DISCUSSION-STATE: OPEN

## Discussion response

**Verdict:** COMMENT

**Reasoning:** The thread still needs product input.

**Required next action:** Wait for a specific persona response.
"""

    assert agent_output_validator.infer_action(body, github_event_name="discussion_comment") == "comment_discussion"


def test_discussion_state_closed_infers_close_discussion():
    assert agent_output_validator.infer_action(VALID_CLOSE_DISCUSSION, github_event_name="discussion_comment") == "close_discussion"


def test_create_issue_marker_is_validated():
    body = """---
Persona: Ari
Role: AI Orchestrator
Layer: executive
Model: claude-sonnet-4-6
Source: Team request issue #42
Self-review conflict: No
Run-ID: 2026-05-23T07:00:00Z-ari-create-issue
---

ISSUE-STATE: CREATED

## Source
Issue #42

## Problem
The team needs paid invoices exported as CSV.

## Acceptance criteria
- [ ] Export paid invoices as CSV from the billing screen.
"""

    inferred = agent_output_validator.infer_action(body)
    result = agent_output_validator.validate_agent_output(body, action=inferred, persona_id="ari-orchestrator")

    assert inferred == "create_issue"
    assert result.valid, result.errors
