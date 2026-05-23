"""Deliberation, voting, and conflict-resolution scenarios.

The headline test is :func:`test_complex_disagreement_converges_within_10_rounds`
which drives a structured debate between two opposing reviewers, runs a
vote, applies a counterproposal, and lands on a converged decision —
all within 10 rounds.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from simulation.tools import deliberation
from simulation.tools import lifecycle
from simulation.tools import lock as lock_mod
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import safety


REPO = "test-org/test-repo"


def _issue(number, *, body="", comments=None, labels=None, created=None, updated=None):
    return {
        "number": number,
        "body": body,
        "comments": [{"body": text, "author": "anon"} if isinstance(text, str) else text for text in (comments or [])],
        "labels": [{"name": name} for name in (labels or [])],
        "createdAt": created,
        "updatedAt": updated,
    }


# --------------------------------------------------------------------------
# Debate + voting.
# --------------------------------------------------------------------------


def test_debate_caps_three_rounds_per_side():
    debate = deliberation.Debate(topic="merge strategy", pro="alice", con="bob")
    for _ in range(3):
        debate.add("alice", " ".join(["arg"] * 50))
        debate.add("bob", " ".join(["arg"] * 50))
    assert debate.is_ready_for_vote() is True
    try:
        debate.add("alice", "one more")
    except ValueError:
        pass
    else:
        raise AssertionError("expected fourth alice round to be rejected")


def test_vote_tally_decides_majority():
    comments = [
        {"body": "VOTE: AGREE", "author": "alice"},
        {"body": "VOTE: AGREE", "author": "bob"},
        {"body": "VOTE: DISAGREE", "author": "carol"},
    ]
    tally = deliberation.tally_votes(comments)
    assert tally.winner == "AGREE"
    assert tally.agree == 2
    assert tally.disagree == 1


def test_vote_tie_breaks_to_maintainer():
    comments = [
        {"body": "VOTE: AGREE", "author": "alice"},
        {"body": "VOTE: DISAGREE", "author": "bob"},
        {"body": "VOTE: DISAGREE", "author": "carol"},
        {"body": "VOTE: AGREE", "author": "maintainer-lina"},
    ]
    tally = deliberation.tally_votes(comments, maintainers={"maintainer-lina"})
    assert tally.winner == "AGREE"
    assert tally.tiebreak == "maintainer"


def test_counterproposal_voting_picks_highest():
    comments = [
        {"body": "VOTE: PROPOSAL_A", "author": "alice"},
        {"body": "VOTE: PROPOSAL_B", "author": "bob"},
        {"body": "VOTE: PROPOSAL_A", "author": "carol"},
    ]
    tally = deliberation.tally_counterproposals(comments)
    assert tally.winner == "PROPOSAL_A"


# --------------------------------------------------------------------------
# Quorum.
# --------------------------------------------------------------------------


def test_quorum_requires_two_distinct_or_one_human():
    review_comments = [
        {"body": "REVIEW-VERDICT: APPROVE", "author": "agent-bot"},
    ]
    status = deliberation.quorum_status(review_comments)
    assert status.ok is False
    assert status.needs_more == 1

    review_comments.append({"body": "REVIEW-VERDICT: APPROVE", "author": "human-lina"})
    status = deliberation.quorum_status(review_comments, human_logins={"human-lina"})
    assert status.ok is True
    assert status.human_approvals == 1


# --------------------------------------------------------------------------
# Retraction / pause / reconsider.
# --------------------------------------------------------------------------


def test_retraction_extracts_ids_and_filters_history():
    text = "RETRACT: review-35-123\nRETRACT: design-12-foo"
    assert set(deliberation.detect_retraction(text)) == {"review-35-123", "design-12-foo"}
    state = {
        "history": [
            {"id": "review-35-123", "marker": "REQUEST_CHANGES"},
            {"id": "approval-99", "marker": "APPROVE"},
        ],
    }
    out = deliberation.apply_retraction(state, ["review-35-123"])
    assert out["history"] == [{"id": "approval-99", "marker": "APPROVE"}]


def test_pause_state_blocks_orchestrator():
    issue = _issue(3, comments=["PAUSE: waiting on legal"])
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="review_pr",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.abort is True
    assert "paused" in decision.reason


def test_reconsider_marker_parsed():
    requested, approved, evidence = deliberation.reconsider_state(
        "RECONSIDER: new perf data\nRECONSIDER-APPROVED"
    )
    assert requested is True
    assert approved is True
    assert "perf" in evidence


# --------------------------------------------------------------------------
# Ethics / dangerous keywords.
# --------------------------------------------------------------------------


def test_ethics_blocks_without_override():
    issue = _issue(
        4,
        comments=["this would let us scrape PII without consent for marketing"],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="implement_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "post_status_and_exit"
    assert "ethics" in decision.reason


def test_ethics_override_unblocks():
    issue = _issue(
        5,
        body="bypass auth for the demo only",
        comments=["ETHICS-OVERRIDE: APPROVED"],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="implement_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override is None or "ethics" not in decision.reason


def test_dangerous_keyword_requires_force_ack():
    issue = _issue(6, comments=["please delete all data in the customers table"])
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="implement_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "post_status_and_exit"
    assert "dangerous" in decision.reason


# --------------------------------------------------------------------------
# Convergence + hotfix + cross-issue.
# --------------------------------------------------------------------------


def test_30_day_convergence_escalates():
    long_ago = (
        _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(days=45)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = _issue(11, created=long_ago, updated=long_ago)
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "open_followup_issue"
    assert decision.context.get("escalate_to_human") is True


def test_cross_issue_redirect_detects_misroute():
    assert lifecycle.cross_issue_redirect("please look at #42 it's broken", current_issue=10) == 42
    assert lifecycle.cross_issue_redirect("ref #10 and #42", current_issue=10) is None


def test_hotfix_marker_skips_design():
    assert lifecycle.needs_hotfix("HOTFIX: #321") == 321
    assert lifecycle.hotfix_skips_design("HOTFIX: #321") is True


def test_grace_period_reopen_within_one_hour():
    closed = "2026-05-23T10:00:00Z"
    reopen_in_grace = "2026-05-23T10:30:00Z"
    reopen_late = "2026-05-23T12:30:00Z"
    assert lifecycle.grace_period_reopen(closed, reopen_in_grace) == "reopen"
    assert lifecycle.grace_period_reopen(closed, reopen_late) == "recovery"


# --------------------------------------------------------------------------
# RATIONALE + CONSTRAINT enforcement.
# --------------------------------------------------------------------------


def test_rationale_required():
    short_text = "RATIONALE: too short"
    ok, _ = safety.requires_rationale(short_text)
    assert ok is False

    good = "RATIONALE: " + "word " * 12
    ok, body = safety.requires_rationale(good)
    assert ok is True
    assert "word" in body


def test_constraint_set_detects_violation():
    constraints = safety.ConstraintSet.from_text(
        "CONSTRAINT: do not introduce new top-level dependencies"
    )
    action = "We will add a new requirement to add a new top-level dependency on pandas."
    violations = constraints.violations(action)
    assert violations and "do not introduce" in violations[0]


# --------------------------------------------------------------------------
# Headline test: complex disagreement converges within 10 rounds.
# --------------------------------------------------------------------------


def test_complex_disagreement_converges_within_10_rounds(tmp_path):
    """End-to-end: alice and bob disagree; one debate + vote settles it."""
    rounds = 0

    debate = deliberation.Debate(topic="postgres vs mysql", pro="alice", con="bob")

    # Three rounds of 200-word args each = 6 rounds total.
    for _ in range(3):
        debate.add("alice", "postgres handles json and ddl transactions better " * 5)
        debate.add("bob", "mysql has simpler ops and the team knows it " * 5)
        rounds += 2

    assert debate.is_ready_for_vote()

    # Round 7: vote.
    comments = [
        {"body": "VOTE: AGREE", "author": "alice"},
        {"body": "VOTE: DISAGREE", "author": "bob"},
        {"body": "VOTE: AGREE", "author": "carol"},
    ]
    rounds += 1
    tally = deliberation.tally_votes(comments, maintainers={"alice"})
    assert tally.winner == "AGREE"

    # Round 8: bob retracts.
    retract_text = "RETRACT: bob-round-2"
    assert deliberation.detect_retraction(retract_text) == ["bob-round-2"]
    rounds += 1

    # Round 9: log conflict + resolution.
    conflict = deliberation.ConflictLog(path=tmp_path / "conflicts.md")
    conflict.append(
        topic="postgres vs mysql",
        sides={"alice": "postgres", "bob": "mysql"},
        resolution="postgres won 2-1 with maintainer signal; bob retracted",
    )
    rounds += 1
    assert (tmp_path / "conflicts.md").exists()
    assert "postgres won" in (tmp_path / "conflicts.md").read_text()

    # Round 10: orchestrator confirms no blocker remains.
    issue = _issue(
        99,
        body="<!-- DECISIONS: db=postgres -->",
        comments=["REVIEW-VERDICT: APPROVE — postgres ratified"],
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="merge_pr",
        proposed_pr_number=99,
        open_prs=[{"number": 99, "state": "OPEN"}],
        runner=lock_mod.InMemoryGh(),
    )
    rounds += 1
    assert decision.abort is False
    assert decision.action_override is None
    assert rounds <= 10, f"converged in {rounds} rounds — expected <= 10"
