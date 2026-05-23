from simulation.tools import validate_agent_action as validator


VALID_HEADER = """---
Persona: mara-product-owner
Role: AI Product Owner
Layer: Executive
Model: claude-opus-4-7-1m
Source: PR #35 diff + PR body
Self-review conflict: No
Run-ID: 2026-05-23T00:00:00Z-test-mara
---
"""


def test_valid_pr_review_passes():
    text = VALID_HEADER + """
**Verdict:** COMMENT

**Acceptance matrix:**
| Criterion | Status | Evidence (path:line or MISSING) |
| --- | --- | --- |
| Idea Lab serves user need | PASS | docs/idea-lab.md:1 |

**Blocking findings:**
1. none

**Non-blocking findings:**
1. The promotion gate should be monitored after launch.

**Required next action:** Rerun next_prompt.py for the next reviewer.

**Fallibility statement:** This review may be wrong; verify against the diff and issue acceptance criteria.
"""

    result = validator.validate(text, kind="pr-review", persona="mara-product-owner")

    assert result.ok, result.errors
    assert result.detected_persona == "mara-product-owner"
    assert result.detected_verdict == "COMMENT"


def test_pr_review_rejects_wrong_persona_and_placeholder():
    text = VALID_HEADER.replace("mara-product-owner", "iris-security") + """
**Verdict:** COMMENT

**Acceptance matrix:**
| Criterion | Status | Evidence (path:line or MISSING) |
| --- | --- | --- |
| CHANGE_ME | PASS | docs/idea-lab.md:1 |

**Blocking findings:**
1. none

**Non-blocking findings:**
1. none

**Required next action:** CHANGE_ME
"""

    result = validator.validate(text, kind="pr-review", persona="mara-product-owner")

    assert not result.ok
    assert any("Persona mismatch" in error for error in result.errors)
    assert any("CHANGE_ME" in error for error in result.errors)


def test_valid_discussion_comment_passes():
    text = VALID_HEADER + """
**Discussion state:** RESOLVED

**Response:** The question has enough information and no new issue is needed.

**Evidence from discussion:**
1. The latest comment says the answer was accepted.

**Required next action:** No action needed.

**Lifecycle marker:** DISCUSSION-STATE: RESOLVED
"""

    result = validator.validate(text, kind="discussion-comment", persona="mara-product-owner")

    assert result.ok, result.errors
    assert result.detected_marker == "DISCUSSION-STATE: RESOLVED"


def test_acceptance_decision_requires_machine_marker():
    text = VALID_HEADER + """
ACCEPTANCE-DECISION: ACCEPT PR#35 -- quorum satisfied and no blocking findings remain

**Decision:** ACCEPT

**Gate evidence:**
| Gate | Status | Evidence |
| --- | --- | --- |
| Required reviews | PASS | PR comments |

**Reason:** Required reviews are present and no blocker remains.

**Next action:** Rerun next_prompt.py; it should select merge_pr.
"""

    result = validator.validate(text, kind="acceptance-decision", persona="mara-product-owner")

    assert result.ok, result.errors
    assert result.detected_marker == "ACCEPTANCE-DECISION: ACCEPT"


def test_auto_detects_discussion_comment():
    text = VALID_HEADER + """
**Discussion state:** DEFERRED

**Response:** Not now.

**Evidence from discussion:**
1. The prerequisite issue is not complete.

**Required next action:** Revisit after the prerequisite closes.

**Lifecycle marker:** DISCUSSION-STATE: DEFERRED
"""

    result = validator.validate(text, kind="auto", persona="mara-product-owner")

    assert result.ok, result.errors
    assert result.kind == "discussion-comment"
