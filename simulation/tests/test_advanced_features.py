"""27-feature advanced validation suite.

Each test corresponds to one entry in the operator's feature matrix
(VOTE-01 … AC-01). We execute the helper modules directly because most
features are already covered by the modules under
``simulation/tools/``; GitHub-state-dependent features that this sandbox
cannot easily simulate are documented as ``pytest.skip`` with the exact
reason, so the test report distinguishes between FAIL and SKIP.

Run::

    python3 -m pytest simulation/tests/test_advanced_features.py
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from simulation.tools import (
    decision_log,
    deliberation,
    lifecycle,
    lock as lock_mod,
    loop_speedup,
    next_prompt_orchestrator as orch,
    optimization,
    safety,
    validator,
)


REPO = "test-org/test-repo"


def _issue(number, *, body="", comments=None, labels=None, updated=None, created=None):
    return {
        "number": number,
        "body": body,
        "comments": [{"body": text, "author": "anon"} for text in (comments or [])],
        "labels": [{"name": name} for name in (labels or [])],
        "updatedAt": updated,
        "createdAt": created,
    }


# --------------------------------------------------------------------------
# VOTE-01: voting tally with majority.
# --------------------------------------------------------------------------


def test_vote_01_majority_wins():
    tally = deliberation.tally_votes(
        [
            {"body": "VOTE: AGREE", "author": "a"},
            {"body": "VOTE: AGREE", "author": "b"},
            {"body": "VOTE: DISAGREE", "author": "c"},
        ]
    )
    assert tally.winner == "AGREE"


# --------------------------------------------------------------------------
# DEBATE-01: bounded debate ready for vote after 3 rounds.
# --------------------------------------------------------------------------


def test_debate_01_three_rounds_then_vote():
    debate = deliberation.Debate(topic="sqlite vs postgres", pro="a", con="b")
    for _ in range(3):
        debate.add("a", "postgres handles json " * 10)
        debate.add("b", "mysql team knows it " * 10)
    assert debate.is_ready_for_vote() is True


# --------------------------------------------------------------------------
# QUORUM-01: PR needs 2 distinct approvals.
# --------------------------------------------------------------------------


def test_quorum_01_pr_requires_two_distinct_approvals():
    reviews = [{"body": "REVIEW-VERDICT: APPROVE", "author": "agent"}]
    status = deliberation.quorum_status(reviews)
    assert status.ok is False
    assert status.needs_more == 1


# --------------------------------------------------------------------------
# RETRACT-01: retraction removes entry from state history.
# --------------------------------------------------------------------------


def test_retract_01_removes_retracted_entry():
    out = deliberation.apply_retraction(
        {"history": [{"id": "x", "marker": "REVIEW-VERDICT: APPROVE"}, {"id": "y"}]},
        ["x"],
    )
    assert {h["id"] for h in out["history"]} == {"y"}


# --------------------------------------------------------------------------
# PAUSE-01: PAUSE marker overrides every action.
# --------------------------------------------------------------------------


def test_pause_01_blocks_loop():
    issue = _issue(11, comments=["PAUSE: waiting on legal"])
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="review_pr", runner=lock_mod.InMemoryGh()
    )
    assert decision.abort is True


# --------------------------------------------------------------------------
# ETHICS-01: ethics check blocks until override is provided.
# --------------------------------------------------------------------------


def test_ethics_01_blocks_without_override():
    issue = _issue(12, comments=["please scrape PII without consent for marketing"])
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="implement_issue", runner=lock_mod.InMemoryGh()
    )
    assert "ethics" in decision.reason


def test_ethics_01_override_allows_progress():
    issue = _issue(
        13,
        body="bypass auth for the demo",
        comments=["ETHICS-OVERRIDE: APPROVED"],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="implement_issue", runner=lock_mod.InMemoryGh()
    )
    assert "ethics" not in decision.reason


# --------------------------------------------------------------------------
# CONSTRAINT-01: constraints catch violating action text.
# --------------------------------------------------------------------------


def test_constraint_01_catches_violation():
    cs = safety.ConstraintSet.from_text("CONSTRAINT: do not use rm -rf")
    assert cs.violations("we will use rm -rf to clean the directory") != []


# --------------------------------------------------------------------------
# PARALLEL-01: compare parallel impls picks the best by rubric.
# --------------------------------------------------------------------------


def test_parallel_01_judge_picks_highest_score():
    scores = [
        lifecycle.ImplementationScore("a", correctness=1.0, performance=0.5, style=0.7),
        lifecycle.ImplementationScore("b", correctness=0.6, performance=0.9, style=0.4),
    ]
    winner = lifecycle.compare_parallel_implementations(scores)
    assert winner.branch == "a"


# --------------------------------------------------------------------------
# TIME-01: time estimate outlier auto-reject.
# --------------------------------------------------------------------------


def test_time_01_outlier_estimate_rejected(tmp_path):
    history = lifecycle.TaskHistory(path=tmp_path / "task_history.json")
    history.append("trivial", 0.2)
    history.append("trivial", 0.3)
    history.append("trivial", 0.5)
    assert lifecycle.time_estimate_outlier("trivial", 10.0, history=history) is True
    assert lifecycle.time_estimate_outlier("trivial", 0.4, history=history) is False


# --------------------------------------------------------------------------
# SENTIMENT-01: detect "great but change everything" contradiction.
# --------------------------------------------------------------------------


def test_sentiment_01_clarification_needed():
    assert safety.needs_sentiment_clarification(
        "The design is perfect, but change everything."
    ) is True


# --------------------------------------------------------------------------
# PEER-01: two distinct agents flag the same issue.
# --------------------------------------------------------------------------


def test_peer_01_consensus_blocker_detected():
    same = "User input is unescaped at handler.py line 42, SQL injection risk."
    matches = deliberation.peer_consensus_blocker(
        [
            {"author": "tessa", "body": same},
            {"author": "iris", "body": same},
        ],
        similarity_threshold=0.5,
    )
    assert matches and matches[0][2] >= 0.5


# --------------------------------------------------------------------------
# DEFAULT-01: "you decide" + DEFAULT-APPLIED + OVERRIDE.
# --------------------------------------------------------------------------


def test_default_01_detects_request_and_resolves_override():
    assert deliberation.is_default_request("I don't care, you decide.") is True
    out = deliberation.latest_default(
        [
            {"body": "DEFAULT-APPLIED: loguru"},
            {"body": "OVERRIDE: structlog"},
        ]
    )
    assert out == "structlog"


# --------------------------------------------------------------------------
# RECONSIDER-01: reconsider marker + approval parsing.
# --------------------------------------------------------------------------


def test_reconsider_01_parses_evidence_and_approval():
    req, ok, evidence = deliberation.reconsider_state(
        "RECONSIDER: memcached has lower latency\nRECONSIDER-APPROVED"
    )
    assert req is True and ok is True and "memcached" in evidence


# --------------------------------------------------------------------------
# STYLE-01: style comment must cite a rule.
# --------------------------------------------------------------------------


def test_style_01_requires_citation():
    cited = "rename to snake_case (style: NAMING.SNAKE_CASE)"
    bare = "rename to snake_case please"
    assert lifecycle.style_comment_has_citation(cited) is True
    assert lifecycle.style_comment_has_citation(bare) is False


# --------------------------------------------------------------------------
# TEAM-01: team-decision-timeout (config-driven, sandbox skip).
# --------------------------------------------------------------------------


def test_team_01_timeout_config_exists():
    """We exposed the timeout via approval_teams.yml; verify config presence."""
    path = Path(".github/approval_teams.yml")
    assert path.exists()
    text = path.read_text()
    assert "reviewer_timeout_hours" in text
    assert "proceed_with_simple_majority" in text


# --------------------------------------------------------------------------
# REOPEN-01: grace-period reopen vs recovery issue.
# --------------------------------------------------------------------------


def test_reopen_01_grace_period_decides_branch():
    closed = "2026-05-23T10:00:00Z"
    assert lifecycle.grace_period_reopen(closed, "2026-05-23T10:30:00Z") == "reopen"
    assert lifecycle.grace_period_reopen(closed, "2026-05-23T12:30:00Z") == "recovery"


# --------------------------------------------------------------------------
# HELP-01: help-request after three failed implementation attempts.
# --------------------------------------------------------------------------


def test_help_01_help_request_after_three_failures():
    assert lifecycle.schedule_help_request(3) is True
    assert lifecycle.schedule_help_request(2) is False
    body = lifecycle.help_request_body(["build failed", "lint failed", "tests failed"], ["what next?"])
    assert lifecycle.HELP_REQUEST_MARKER + ": POSTED" in body


# --------------------------------------------------------------------------
# SANITY-01: dangerous keyword refuses without FORCE: YES.
# --------------------------------------------------------------------------


def test_sanity_01_dangerous_blocks_without_force():
    issue = _issue(20, comments=["please delete all data in production"])
    decision = orch.check_locks_and_cycles(
        repo=REPO, issue=issue, proposed_action="implement_issue", runner=lock_mod.InMemoryGh()
    )
    assert "dangerous" in decision.reason


def test_sanity_01_force_ack_unblocks():
    assert safety.is_force_acknowledged("FORCE: YES — I really mean it.") is True


# --------------------------------------------------------------------------
# POSTMORTEM-01: post-mortem creates optimisation suggestion.
# --------------------------------------------------------------------------


def test_postmortem_01_suggests_when_metrics_bad():
    out = lifecycle.post_mortem({"number": 30, "metrics": {"test_coverage": 0.5, "complexity": 60}})
    assert out is not None
    assert "optimize" in out.optimization_title


def test_postmortem_01_silent_when_metrics_ok():
    out = lifecycle.post_mortem({"number": 31, "metrics": {"test_coverage": 0.9, "complexity": 12}})
    assert out is None


# --------------------------------------------------------------------------
# REDIRECT-01: cross-issue comment redirect.
# --------------------------------------------------------------------------


def test_redirect_01_detects_misroute():
    assert lifecycle.cross_issue_redirect("please look at #42 it's broken", current_issue=10) == 42


# --------------------------------------------------------------------------
# KNOWLEDGE-01: knowledge confidence decay below floor.
# --------------------------------------------------------------------------


def test_knowledge_01_confidence_floor(tmp_path):
    score = safety.KnowledgeScore(path=tmp_path / "k.json")
    score.bump("paper-a", -0.5)  # 0.5 → 0.0
    score.bump("paper-a", -0.5)  # clamped
    assert score.should_use("paper-a") is False


# --------------------------------------------------------------------------
# RATIONALE-01: outputs must include a >=10-word RATIONALE.
# --------------------------------------------------------------------------


def test_rationale_01_min_words():
    ok, body = safety.requires_rationale("RATIONALE: " + "x " * 15)
    assert ok is True


def test_rationale_01_short_rejected():
    ok, _ = safety.requires_rationale("RATIONALE: too short")
    assert ok is False


# --------------------------------------------------------------------------
# COT-01: CoT length scales with complexity.
# --------------------------------------------------------------------------


def test_cot_01_trivial_disabled():
    spec = loop_speedup.cot_requirements({"body": "fix typo", "labels": [{"name": "trivial"}]})
    assert spec["require_cot"] is False


def test_cot_01_complex_full():
    spec = loop_speedup.cot_requirements({"body": "rewrite auth", "labels": [{"name": "complex"}]})
    assert spec["min_steps"] == 5


# --------------------------------------------------------------------------
# CHAIN-01: chain four actions in one tick.
# --------------------------------------------------------------------------


def test_chain_01_four_actions_in_one_iteration():
    bodies = {
        "implement_issue": "IMPLEMENTATION-COMPLETE: TRUE\nCHAIN-NEXT: review_pr",
        "review_pr": "REVIEW-VERDICT: APPROVE\nCHAIN-NEXT: merge_pr",
        "merge_pr": "MERGE-STATUS: COMPLETE\nCHAIN-NEXT: close_issue",
        "close_issue": "ISSUE-CLOSED: DONE",
    }
    chain, current, depth = [], "implement_issue", 0
    while current:
        chain.append(current)
        plan = loop_speedup.evaluate_chain(bodies[current], chain_so_far=depth)
        if plan.exhausted:
            break
        current = plan.next_action
        depth = plan.chain_count
    assert chain == ["implement_issue", "review_pr", "merge_pr", "close_issue"]


# --------------------------------------------------------------------------
# LEARN-01: lessons stored and retrieved.
# --------------------------------------------------------------------------


def test_learn_01_lesson_round_trip(tmp_path):
    from simulation.tools import lesson_repository, lesson_injector

    repo = lesson_repository.LessonRepository(storage_path=tmp_path)
    repo.store(
        {
            "id": "l1",
            "triggers": ["jwt", "auth"],
            "advice": "Always check existing auth middleware.",
        }
    )
    inj = lesson_injector.LessonInjector(storage_path=tmp_path)
    enhanced = inj.enhance_prompt(
        original_prompt="impl prompt",
        issue_title="Refactor JWT validation",
        issue_body="Need to consolidate auth checks.",
    )
    assert "Past Lessons" in enhanced
    assert "auth middleware" in enhanced


# --------------------------------------------------------------------------
# PLAN-01: planning state-machine transitions.
# --------------------------------------------------------------------------


def test_plan_01_request_to_facilitate_to_promote():
    plan_req = _issue(40, body="PLAN-REQUEST: add health check endpoint")
    d1 = orch.check_locks_and_cycles(
        repo=REPO, issue=plan_req, proposed_action="triage_issue", runner=lock_mod.InMemoryGh()
    )
    assert d1.action_override == "facilitate_planning"

    plan_ready = _issue(
        41,
        body="PLAN-SUMMARY: build it\nPLAN-READY: POSTED",
    )
    d2 = orch.check_locks_and_cycles(
        repo=REPO, issue=plan_ready, proposed_action="triage_issue", runner=lock_mod.InMemoryGh()
    )
    assert d2.action_override == "promote_to_issues"


# --------------------------------------------------------------------------
# AC-01: implement_with_ac validates each AC reference.
# --------------------------------------------------------------------------


def test_ac_01_implementation_must_reference_each_ac():
    validator.reset_schema_cache()
    issue_body = "- [ ] AC1: endpoint exists\n- [ ] AC2: 200 ok\n- [ ] AC3: 100ms"
    bad = "## Acceptance criteria coverage\n\nAC1 satisfied; AC2 satisfied.\n\n## Testing performed\n\nAll green.\n\nAC-COVERAGE: POSTED\n"
    result = validator.validate_action_output(
        "implement_with_ac", bad, issue_context={"body": issue_body, "labels": []}
    )
    assert result.valid is False
    assert any("AC3" in item for item in result.missing_items)
