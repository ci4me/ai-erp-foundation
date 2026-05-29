"""Tests for the five-phase feature lifecycle (planning..done).

Plain asserts so the module runs under pytest or a bare harness. Uses the real
analyze_state -> build_plan pipeline with dict-shaped state.
"""

from simulation.tools.plan_builder import build_plan
from simulation.tools.state_analyzer import (
    PHASE_LABELS,
    analyze_state,
    get_current_phase,
    phase_gate_ready,
)


def _issue(number, *, body="", labels=(), comments=(), state="open"):
    return {
        "number": number,
        "title": f"issue {number}",
        "body": body,
        "labels": [{"name": n} for n in labels],
        "comments": [{"body": b} for b in comments],
        "state": state,
        "createdAt": "2026-05-01T00:00:00Z",
    }


def _types(state):
    return [p["type"] for p in analyze_state(state)]


def _wrap(issues):
    return {"prs": [], "discussions": [], "issues": issues}


def test_get_current_phase():
    assert get_current_phase(_issue(1, labels=["epic", "phase/testing"])) == "phase/testing"
    assert get_current_phase(_issue(2, labels=["epic"])) is None


def test_planning_gate_ready_with_consensus_plan_and_approval():
    epic = _issue(
        100,
        labels=["epic", "phase/planning"],
        comments=[
            "CONSENSUS-REACHED: ship it (signees: @theo-architect, @ari-orchestrator)",
            "DECOMPOSITION-PLAN:\nSUB-TASK: a\nSUB-TASK: b",
        ],
    )
    state = _wrap([epic])
    assert phase_gate_ready(state, epic) == PHASE_LABELS["implementation"]
    assert "PHASE_GATE_READY" in _types(state)


def test_planning_not_ready_without_plan():
    epic = _issue(
        100,
        labels=["epic", "phase/planning"],
        comments=["CONSENSUS-REACHED: ship it (signees: @theo-architect, @ari-orchestrator)"],
    )
    # No decomposition plan -> EPIC_UNDECOMPOSED, not a gate.
    types = _types(_wrap([epic]))
    assert "PHASE_GATE_READY" not in types
    assert "EPIC_UNDECOMPOSED" in types


def test_phase_gate_action_generated_for_planning_epic():
    epic = _issue(
        100,
        labels=["epic", "phase/planning"],
        comments=[
            "RESOLUTION: go (approved by ari-orchestrator)",
            "DECOMPOSITION-PLAN:\nSUB-TASK: a\nSUB-TASK: b",
        ],
    )
    plan = build_plan(analyze_state(_wrap([epic])), mode="multi")
    bodies = [s["body"] for s in plan["steps"] if s["target"].get("number") == 100]
    assert any("PHASE-CHANGE:" in b for b in bodies), bodies


def test_implementation_actions_blocked_outside_implementation_phase():
    # A trivial issue stuck in phase/testing must NOT get implementation work.
    issue = _issue(101, labels=["trivial", "phase/testing"], body="do a thing")
    plan = build_plan(analyze_state(_wrap([issue])), mode="multi")
    actions = {(s["target"].get("number"), s["action"]) for s in plan["steps"]}
    # No TRIVIAL_NOT_IMPLEMENTED-driven step should target this issue; only the
    # testing-phase action (run_tests, rendered as comment_issue) may appear.
    impl_like = [a for n, a in [(s["target"].get("number"), s["action"]) for s in plan["steps"]]
                 if n == 101 and a in ("create_pr",)]
    assert impl_like == [], actions


def test_testing_required_triggers_run_tests():
    epic = _issue(102, labels=["epic", "phase/testing"], comments=["DECOMPOSITION-PLAN:\nSUB-TASK: a\nSUB-TASK: b"])
    types = _types(_wrap([epic]))
    assert "TESTING_REQUIRED" in types


def test_testing_pass_gates_to_acceptance():
    epic = _issue(102, labels=["epic", "phase/testing"], comments=["TEST-REPORT: Pass (all green)"])
    state = _wrap([epic])
    assert phase_gate_ready(state, epic) == PHASE_LABELS["acceptance"]
    assert "PHASE_GATE_READY" in _types(state)


def test_acceptance_requires_approval_request_then_waits():
    # No approval request yet -> ACCEPTANCE_REQUIRED.
    epic = _issue(103, labels=["epic", "phase/acceptance"], comments=["TEST-REPORT: Pass"])
    types = _types(_wrap([epic]))
    assert "ACCEPTANCE_REQUIRED" in types
    # Approval requested but not yet answered -> no gate to done (human wait).
    epic2 = _issue(
        103, labels=["epic", "phase/acceptance"],
        comments=["REQUEST-APPROVAL-FROM: @product-owner (ready)"],
    )
    assert phase_gate_ready(_wrap([epic2]), epic2) is None


def test_acceptance_approved_gates_to_done():
    epic = _issue(
        103, labels=["epic", "phase/acceptance"],
        comments=["REQUEST-APPROVAL-FROM: @product-owner", "ACCEPTANCE-DECISION: Approved"],
    )
    assert phase_gate_ready(_wrap([epic]), epic) == PHASE_LABELS["done"]


def test_acceptance_blocked_is_flagged_and_no_gate():
    epic = _issue(
        103, labels=["epic", "phase/acceptance"],
        comments=["ACCEPTANCE-DECISION: Blocked (needs rework)"],
    )
    state = _wrap([epic])
    assert "ACCEPTANCE_BLOCKED" in _types(state)
    assert phase_gate_ready(state, epic) is None
