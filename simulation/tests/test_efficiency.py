"""Token-efficiency / loop-convergence scenario tests.

Covers, per the system-improvement spec:

1. Quick-fix bypass for trivial TEAM-REQUEST issues.
2. Style-only auto-approval after 3 rounds.
3. Off-topic detection routes to a fixed response.
4. Identical-feedback cycle breaker.
5. Multiple markers in one comment respect priority + URGENT moves to front.
"""

from __future__ import annotations

import datetime as _dt

from simulation.tools import decision_log
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import optimization
from simulation.tools import lock as lock_mod


REPO = "test-org/test-repo"


def _issue(number, *, body="", title="", comments=None, labels=None, updated=None):
    return {
        "number": number,
        "title": title,
        "body": body,
        "comments": [{"body": text} for text in (comments or [])],
        "labels": [{"name": name} for name in (labels or [])],
        "updatedAt": updated,
    }


# --------------------------------------------------------------------------
# 1. Quick-fix bypass.
# --------------------------------------------------------------------------


def test_quick_fix_bypass_skips_triage_and_design():
    issue = _issue(
        1,
        title="typo in README",
        body="TEAM-REQUEST: fix the typo in README intro paragraph",
        labels=["trivial"],
    )
    assert optimization.quick_fix_bypass(issue) is True
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "implement_issue"
    assert decision.context["quick_fix"] is True


def test_quick_fix_bypass_does_not_fire_without_team_request():
    issue = _issue(2, title="fix typo", labels=["trivial"])
    assert optimization.quick_fix_bypass(issue) is False


# --------------------------------------------------------------------------
# 2. Style-only approval limit.
# --------------------------------------------------------------------------


def test_style_only_review_detection():
    text = "Please fix whitespace and naming of foo_bar; add docstring."
    assert optimization.is_style_only_review(text) is True


def test_style_only_review_ignores_logic_changes():
    text = "Naming is fine but there's a bug in the auth logic causing a crash."
    assert optimization.is_style_only_review(text) is False


def test_style_round_auto_approves_after_three():
    assert optimization.should_auto_approve_style(2) is False
    assert optimization.should_auto_approve_style(3) is True
    labels = ["risk:low", "style_round:3"]
    assert optimization.style_round_count(labels) == 3
    assert optimization.should_auto_approve_style(optimization.style_round_count(labels)) is True


# --------------------------------------------------------------------------
# 3. Off-topic detection.
# --------------------------------------------------------------------------


def test_off_topic_detection_flags_unrelated_chitchat():
    assert optimization.detect_off_topic("Did you see the weather today?") is True
    assert optimization.detect_off_topic("This PR adds a new endpoint.") is False


# --------------------------------------------------------------------------
# 4. Identical-feedback cycle breaking.
# --------------------------------------------------------------------------


def test_identical_feedback_routes_to_close_unresolved():
    history = [
        "REVIEW-VERDICT: REQUEST_CHANGES\nPlease split the migration into two files.",
        "REVIEW-VERDICT: REQUEST_CHANGES\nPlease split the migration into two files.",
    ]
    assert optimization.detect_identical_feedback(history) is True

    issue = _issue(
        5,
        comments=history,
    )
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="address_changes_requested",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert "Identical feedback" in decision.context["close_comment"]


def test_identical_feedback_negative():
    history = [
        "REVIEW-VERDICT: REQUEST_CHANGES\nAdd index on user_id.",
        "REVIEW-VERDICT: REQUEST_CHANGES\nNow also fix the failing test.",
    ]
    assert optimization.detect_identical_feedback(history) is False


# --------------------------------------------------------------------------
# 5. Multiple markers in one comment; URGENT moves to front.
# --------------------------------------------------------------------------


def test_multiple_markers_ranked_by_priority():
    body = (
        "ISSUE-STATE: CREATED\n"
        "REVIEW-VERDICT: APPROVE\n"
        "TEAM-REQUEST: hotfix the broken header logo\n"
    )
    hits = optimization.extract_markers_priority(body)
    markers_in_order = [hit.marker for hit in hits]
    # TEAM-REQUEST first, then REVIEW-VERDICT, then ISSUE-STATE.
    assert markers_in_order[0] == "TEAM-REQUEST"
    assert "REVIEW-VERDICT" in markers_in_order
    assert "ISSUE-STATE" in markers_in_order
    assert markers_in_order.index("REVIEW-VERDICT") < markers_in_order.index("ISSUE-STATE")


def test_urgent_marker_moves_to_front():
    body = "REVIEW-VERDICT: APPROVE\nURGENT: production down\n"
    hits = optimization.extract_markers_priority(body)
    assert hits[0].marker == "URGENT"


# --------------------------------------------------------------------------
# Bonus: stale clarification, state hash, intent classifier, decision log.
# --------------------------------------------------------------------------


def test_stale_clarification_closes_after_48_hours():
    long_ago = (
        _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(hours=72)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = _issue(7, labels=["awaiting-human"], updated=long_ago)
    assert optimization.is_stale_clarification(issue) is True
    decision = orch.check_locks_and_cycles(
        repo=REPO,
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert decision.action_override == "close_issue"
    assert decision.context["issue_close_reason"] == "INACTIVE"


def test_state_hash_breaks_loop_when_stuck():
    s1 = optimization.state_hash(
        {"phase": "design", "design_loop_count": 1, "last_marker": "REQUEST_CHANGES"}
    )
    s2 = optimization.state_hash(
        {"phase": "design", "design_loop_count": 1, "last_marker": "REQUEST_CHANGES"}
    )
    assert s1 == s2
    assert optimization.should_break_loop(3) is True
    labels = ["stuck_counter:3"]
    assert optimization.stuck_count(labels) == 3


def test_intent_classifier_suggests_marker_for_prose():
    guess = optimization.classify_intent("LGTM, please merge whenever")
    assert guess is not None
    assert guess.suggested_marker.startswith("REVIEW-VERDICT")
    assert guess.confidence >= 0.8


def test_intent_classifier_skips_when_marker_already_present():
    guess = optimization.classify_intent("REVIEW-VERDICT: APPROVE — lgtm")
    assert guess is None


def test_decision_log_round_trip():
    body = "Title goes here.\n\n<!-- DECISIONS: database=mysql; frontend=react -->\n"
    log = decision_log.parse_issue_body(body)
    assert log.get("database") == "mysql"
    assert log.get("frontend") == "react"

    conflict = log.conflicts_with({"database": "postgres"})
    assert conflict == {"database": ("mysql", "postgres")}

    log.set("database", "postgres")
    updated = decision_log.write_to_body(body, log)
    assert "database=postgres" in updated


def test_truncate_history_keeps_recent_marked_and_human():
    comments = [
        {"body": "REVIEW-VERDICT: REQUEST_CHANGES old", "createdAt": "2025-01-01T00:00:00Z"},
        {"body": "ack", "createdAt": "2025-01-02T00:00:00Z", "isBot": False},
        {"body": "Persona: foo\nautomated bot reply", "createdAt": "2025-01-03T00:00:00Z"},
    ]
    kept = optimization.truncate_history(comments)
    assert any("REVIEW-VERDICT" in c["body"] for c in kept)
    assert any(c["body"] == "ack" for c in kept)
    # Bot comments without markers are dropped.
    assert not any("automated bot reply" in c["body"] for c in kept)


def test_output_doubled_warns_only_when_significantly_longer():
    assert optimization.output_doubled(100, 300) is True
    assert optimization.output_doubled(100, 150) is False
    assert optimization.output_doubled(0, 1000) is False
