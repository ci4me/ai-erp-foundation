"""Tests for the epic-decomposition + dependency-tracking layer.

Plain asserts so the module runs under pytest or a bare harness. All checks use
the real dict-based analyzer/planner API (analyze_state -> build_plan).
"""

from simulation.tools.plan_builder import build_plan
from simulation.tools.state_analyzer import analyze_state, get_blocking_issues, is_epic


def _issue(number, *, body="", labels=(), comments=()):
    return {
        "number": number,
        "title": f"issue {number}",
        "body": body,
        "labels": [{"name": n} for n in labels],
        "comments": [{"body": b} for b in comments],
        "createdAt": "2026-05-01T00:00:00Z",
    }


def _types(state):
    return [p["type"] for p in analyze_state(state)]


def test_epic_label_is_detected():
    assert is_epic(_issue(1, labels=["epic"]))
    assert not is_epic(_issue(2, labels=["trivial"]))


def test_undecomposed_epic_detected():
    state = {"prs": [], "discussions": [], "issues": [_issue(10, labels=["epic"], body="Big feature")]}
    assert "EPIC_UNDECOMPOSED" in _types(state)


def test_subtasks_not_created_detected():
    epic = _issue(
        11,
        labels=["epic"],
        body="Big feature",
        comments=["DECOMPOSITION-PLAN:\nSUB-TASK: a\nSUB-TASK: b"],
    )
    state = {"prs": [], "discussions": [], "issues": [epic]}
    types = _types(state)
    assert "SUBTASKS_NOT_CREATED" in types
    assert "EPIC_UNDECOMPOSED" not in types


def test_subtasks_created_clears_problem():
    epic = _issue(12, labels=["epic"], comments=["DECOMPOSITION-PLAN:\nSUB-TASK: a\nSUB-TASK: b"])
    child = _issue(13, labels=["sub-task"], body="Parent epic: #12")
    state = {"prs": [], "discussions": [], "issues": [epic, child]}
    types = _types(state)
    assert "SUBTASKS_NOT_CREATED" not in types


def test_dependency_blocks_and_planner_skips_work():
    blocker = _issue(4, body="some work")  # open -> active blocker
    blocked = _issue(5, labels=["trivial"], body="Depends on: #4")
    state = {"prs": [], "discussions": [], "issues": [blocker, blocked]}
    assert get_blocking_issues(state, blocked) == [4]
    assert "BLOCKED_BY_DEPENDENCY" in _types(state)
    # planner must not schedule implementation work on the blocked issue
    plan = build_plan(analyze_state(state), mode="multi")
    blocked_steps = [s for s in plan["steps"] if s["target"].get("number") == 5]
    assert blocked_steps == [], blocked_steps


def test_dependency_resolved_when_blocker_absent():
    # #4 is closed (absent from open-issues state) -> no longer a blocker.
    blocked = _issue(5, labels=["trivial"], body="Depends on: #4")
    state = {"prs": [], "discussions": [], "issues": [blocked]}
    assert get_blocking_issues(state, blocked) == []
    assert "BLOCKED_BY_DEPENDENCY" not in _types(state)


def test_planner_generates_decomposition_action():
    state = {"prs": [], "discussions": [], "issues": [_issue(10, labels=["epic"], body="Big feature")]}
    plan = build_plan(analyze_state(state), mode="multi")
    bodies = [s["body"] for s in plan["steps"] if s["target"].get("number") == 10]
    assert any("DECOMPOSITION-PLAN:" in b for b in bodies), bodies


def test_planner_generates_create_sub_issues_action():
    epic = _issue(11, labels=["epic"], comments=["DECOMPOSITION-PLAN:\nSUB-TASK: a\nSUB-TASK: b"])
    state = {"prs": [], "discussions": [], "issues": [epic]}
    plan = build_plan(analyze_state(state), mode="multi")
    bodies = [s["body"] for s in plan["steps"] if s["target"].get("number") == 11]
    assert any("Parent epic:" in b for b in bodies), bodies
