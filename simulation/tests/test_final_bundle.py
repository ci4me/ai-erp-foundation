"""Final bundle tests — every change shipped together for the autonomous loop.

Verifies, per the deliverable list:

1. ``REVIEW-VERDICT`` accepts ``BLOCKED``.
2. ``run_audit`` schema (with ``AUDIT-STATUS``) passes validation.
3. Duplicate detection prevents the same persona/target/action within 2 h.
4. State hash changes after action.
5. Truncation reduces word count.
6. ``CHAIN-NEXT`` marker triggers inline execution.
7. Trivial issue bypasses CoT.
"""

from __future__ import annotations

import re

from simulation.tools import complexity, context_builder, loop_speedup, validator


# --------------------------------------------------------------------------
# 1. REVIEW-VERDICT accepts BLOCKED (and the widened set).
# --------------------------------------------------------------------------


REVIEW_BLOCKED_BODY = """\
**Reasoning:**
1. Restate the goal: review this PR for the regression in the request handler path.
2. Inspect the diff thoroughly looking for any new code that bypasses the builder utility.
3. Conclude that this PR introduces a string concatenation that we must block immediately.

## Review summary

The PR concatenates raw user input into the query at handler.py:42.
This bypasses our parameterised builder and is a blocking finding.

REVIEW-VERDICT: BLOCKED
"""


def test_review_verdict_accepts_blocked():
    validator.reset_schema_cache()
    result = validator.validate_action_output(
        "review_pr",
        REVIEW_BLOCKED_BODY,
        issue_context={"body": "review the handler PR", "labels": []},
    )
    assert result.valid is True, result.missing_items


# --------------------------------------------------------------------------
# 2. run_audit schema with AUDIT-STATUS.
# --------------------------------------------------------------------------


RUN_AUDIT_BODY = """\
**Reasoning:**
1. Restate the goal: produce an audit of operating-model evidence collected today.
2. Inspect arch_snapshot output for workflow files and persona prompts.
3. Check coverage_matrix for scorecard presence and AC8 evidence.

## Audit findings

Workflows: present. Persona prompts: 33 of 33. Scorecards: 0 of 5 — AC8 unmet.
Recommendation: open follow-up issue for kai-devops to add scorecards.

AUDIT-STATUS: PARTIAL
"""


def test_run_audit_schema_validates_partial():
    validator.reset_schema_cache()
    result = validator.validate_action_output(
        "run_audit",
        RUN_AUDIT_BODY,
        issue_context={"body": "audit operating-model evidence", "labels": []},
    )
    assert result.valid is True, result.missing_items


# --------------------------------------------------------------------------
# 3. Duplicate detection.
# --------------------------------------------------------------------------


def test_dedupe_cache_within_window():
    cache = loop_speedup.DedupeCache(window_minutes=120)
    assert cache.is_duplicate("mara", 35, "review_pr") is False
    cache.record("mara", 35, "review_pr")
    assert cache.is_duplicate("mara", 35, "review_pr") is True
    # different action breaks the dedupe key
    assert cache.is_duplicate("mara", 35, "merge_gate") is False


# --------------------------------------------------------------------------
# 4. State hash changes after action.
# --------------------------------------------------------------------------


def test_state_hash_changes_after_mutation():
    before = loop_speedup.issue_state_hash(
        {"body": "v1", "updatedAt": "2026-05-23T10:00:00Z", "labels": []}
    )
    after = loop_speedup.issue_state_hash(
        {"body": "v1", "updatedAt": "2026-05-23T11:00:00Z", "labels": []}
    )
    assert before != after


def test_state_hash_stable_when_unchanged():
    issue = {"body": "v1", "updatedAt": "2026-05-23T10:00:00Z", "labels": [{"name": "x"}]}
    assert loop_speedup.issue_state_hash(issue) == loop_speedup.issue_state_hash(issue)


# --------------------------------------------------------------------------
# 5. Truncation reduces token count.
# --------------------------------------------------------------------------


def test_truncate_conversation_shrinks_token_count():
    issue_body = "x " * 600  # 1200 chars
    comments = []
    for i in range(20):
        comments.append(
            {
                "body": f"REVIEW-VERDICT: APPROVE reasoning iteration {i}" + " w" * 50,
                "createdAt": f"2026-05-{20+i:02d}T00:00:00Z",
                "author": {"login": f"agent-{i}", "type": "Bot"},
            }
        )
    for i in range(5):
        comments.append(
            {
                "body": "human follow up comment " + " w" * 30,
                "createdAt": f"2026-06-{1+i:02d}T00:00:00Z",
                "author": {"login": f"user-{i}", "type": "User"},
            }
        )
    trimmed, trimmed_body = context_builder.truncate_conversation(comments, issue_body)
    # Hard cap on body works.
    assert len(trimmed_body) <= context_builder.DEFAULT_MAX_BODY_CHARS
    # Comment count drops to at most max_markers + max_human.
    assert len(trimmed) <= context_builder.DEFAULT_MAX_MARKERS + context_builder.DEFAULT_MAX_HUMAN
    saved = context_builder.estimate_token_savings(
        comments, issue_body, trimmed, trimmed_body
    )
    assert saved > 0


# --------------------------------------------------------------------------
# 6. CHAIN-NEXT marker triggers inline execution (chain plan).
# --------------------------------------------------------------------------


def test_chain_next_marker_triggers_followup_action():
    body = "IMPLEMENTATION-COMPLETE: TRUE\nCHAIN-NEXT: review_pr"
    plan = loop_speedup.evaluate_chain(body, chain_so_far=0)
    assert plan.next_action == "review_pr"
    assert plan.chain_count == 1
    assert plan.exhausted is False


def test_chain_next_respects_cap():
    plan = loop_speedup.evaluate_chain(
        "CHAIN-NEXT: review_pr",
        chain_so_far=loop_speedup.MAX_CHAIN,
    )
    assert plan.next_action is None
    assert plan.exhausted is True


# --------------------------------------------------------------------------
# 7. Trivial issue bypasses CoT requirement.
# --------------------------------------------------------------------------


TRIVIAL_OUTPUT_NO_COT = """\
## Implementation

Fixed the typo on README line 12 by replacing the misspelled word with
the correct spelling. No other lines were touched and the diff is a
single character substitution.

## Changes made

- README.md updated at line 12 with the corrected spelling

IMPLEMENTATION-COMPLETE: TRUE
"""


def test_trivial_label_skips_cot_requirement():
    validator.reset_schema_cache()
    result = validator.validate_action_output(
        "implement_issue",
        TRIVIAL_OUTPUT_NO_COT,
        issue_context={"body": "fix typo", "labels": [{"name": "trivial"}]},
    )
    # CoT validation is bypassed for trivial issues; the only missing items
    # should be unrelated to Reasoning.
    assert all("Reasoning" not in item for item in result.missing_items)
    assert result.valid is True, result.missing_items


def test_complex_label_demands_cot():
    validator.reset_schema_cache()
    result = validator.validate_action_output(
        "implement_issue",
        TRIVIAL_OUTPUT_NO_COT,
        issue_context={"body": "rewrite auth", "labels": [{"name": "complex"}]},
    )
    assert result.valid is False
    assert any("Reasoning" in item for item in result.missing_items)


# --------------------------------------------------------------------------
# 8. Get_cot_requirements alias in complexity.py.
# --------------------------------------------------------------------------


def test_get_cot_requirements_trivial():
    spec = complexity.get_cot_requirements({"body": "fix typo", "labels": ["trivial"]})
    assert spec["require_cot"] is False
    assert spec["min_steps"] == 1


def test_get_cot_requirements_complex():
    spec = complexity.get_cot_requirements({"body": "rewrite auth", "labels": ["complex"]})
    assert spec["require_cot"] is True
    assert spec["min_steps"] == 5


def test_get_cot_requirements_medium_default():
    spec = complexity.get_cot_requirements({"body": "add banner", "labels": []})
    assert spec["min_steps"] == 3
    assert spec["require_cot"] is True


# --------------------------------------------------------------------------
# 9. Cacheable prefix split via <!-- CACHE --> sentinel.
# --------------------------------------------------------------------------


def test_cache_sentinel_round_trips_via_llm_client():
    from simulation.tools.llm_client import LlmClient

    client = LlmClient(model="claude-opus-4-7", api_key="dummy")
    content = client._build_content("HEADER\n<!-- CACHE -->\nDYNAMIC TAIL")
    assert len(content) == 2
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "DYNAMIC" in content[1]["text"]
