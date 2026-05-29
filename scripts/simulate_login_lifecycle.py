#!/usr/bin/env python3
"""Drive the login-feature lifecycle simulation over an evolving fixture.

Each stage mutates the in-memory state to reflect what executing the previous
planner step (plus the relevant human/agent action) would produce, then re-runs
analyze_state -> build_plan and records the planner's top action. Pure dry-run.
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from simulation.tools.state_analyzer import analyze_state  # noqa: E402
from simulation.tools.plan_builder import build_plan, _phase_allows, _FIXERS  # noqa: E402

LOG = []

# Map the driving problem type to the logical lifecycle action it triggers.
LOGICAL = {
    "TEAM_REQUEST_UNPROCESSED": "create_issue",
    "EPIC_UNDECOMPOSED": "decompose_feature",
    "SUBTASKS_NOT_CREATED": "create_sub_issues",
    "UNRESOLVED_DEBATE": "resolve_debate",
    "PHASE_GATE_READY": "phase_gate",
    "TESTING_REQUIRED": "run_tests",
    "TESTING_FAILED": "triage_test_failures",
    "ACCEPTANCE_REQUIRED": "acceptance_review",
    "ACCEPTANCE_BLOCKED": "rework_from_rejection",
    "BLOCKED_BY_DEPENDENCY": "(blocked: no action)",
}

def step(label, state, expect_wait=False):
    probs = analyze_state(state)
    plan = build_plan(probs, mode="single")
    top = plan["steps"][0] if plan["steps"] else None
    # The driving problem = the one the single-mode planner acted on (the
    # highest-priority problem whose target matches the emitted step).
    ptypes = [f"{p['type']}(p{p['priority']})" for p in probs]
    # Replicate build_plan's selection: first priority-sorted problem that has a
    # fixer, passes phase suppression, and isn't on a dependency-blocked issue.
    blocked = {p["target"].get("number") for p in probs if p["type"] == "BLOCKED_BY_DEPENDENCY"}
    driver = None
    if top:
        for p in sorted(probs, key=lambda x: x["priority"]):
            t = p["target"]
            if p["type"] not in _FIXERS:
                continue
            if t.get("type") == "issue" and t.get("number") in blocked:
                continue
            if not _phase_allows(p):
                continue
            driver = p["type"]; break
    logical = LOGICAL.get(driver, driver or "—")
    phase = next((l["name"] for i in state["issues"] for l in i.get("labels", [])
                  if l["name"].startswith("phase/")), "—")
    if top:
        LOG.append((label, top["persona"], logical, top["target"].get("number"), phase))
        print(f"{label}\n   phase={phase} problems={ptypes}\n   NEXT: {top['persona']} | {logical} | target #{top['target'].get('number')}")
    else:
        LOG.append((label, "—", "(human wait / done)", "—", phase))
        print(f"{label}\n   phase={phase} problems={ptypes}\n   NEXT: (HUMAN WAIT / terminal)")
    print()

def issue(n, body, labels, comments=(), state="open"):
    return {"number": n, "title": f"#{n}", "body": body,
            "labels": [{"name": l} for l in labels],
            "comments": [{"body": c} for c in comments],
            "state": state, "createdAt": "2026-05-29T00:00:00Z"}

disc = {"number": 1, "title": "Add a login feature",
        "body": "TEAM-REQUEST: Add a login feature (email/password + OAuth) to my app.",
        "comments": [], "createdAt": "2026-05-29T00:00:00Z"}

print("="*70)
print("LOGIN-FEATURE LIFECYCLE SIMULATION (dry-run, fixture-driven)")
print("="*70 + "\n")

# Stage 0: fresh TEAM-REQUEST discussion only.
st = {"prs": [], "issues": [], "discussions": [disc]}
step("S0 fresh request (discussion #1)", st)

# Stage 1: issue #100 created from the request, triaged as epic in planning.
# The epic restates the request marker, so MISSING_MARKER does not fire.
epic_body = ("TEAM-REQUEST: Add a login feature (email/password + OAuth).\n"
             "From discussion #1")
st["issues"] = [issue(100, epic_body, ["epic", "phase/planning"])]
step("S1 issue #100 opened + triaged (epic, phase/planning)", st)

# Stage 2: design debate underway (no resolution yet, recent => not timed out).
st["issues"][0]["comments"] = [
    {"body": "ARGUMENT: use bcrypt + short-lived JWT sessions.",
     "createdAt": "2026-05-29T01:00:00Z"},
    {"body": "COUNTER-PROPOSAL: server-side sessions over JWT (replaces ARGUMENT).",
     "createdAt": "2026-05-29T01:05:00Z"},
]
step("S2 design debate active (recent, within timeout)", st)

# Stage 3: consensus + decomposition plan + approval requested + approved.
st["issues"][0]["comments"] += [
    {"body": "CONSENSUS-REACHED: bcrypt + server-side sessions + OAuth via provider SDK "
             "(signees: @theo-architect, @iris-security)"},
    {"body": "DECOMPOSITION-PLAN:\nSUB-TASK: email/password auth\nSUB-TASK: OAuth flow\nSUB-TASK: session store"},
    {"body": "REQUEST-APPROVAL-FROM: @product-owner"},
]
step("S3 consensus + plan + approval requested (awaiting human)", st, expect_wait=False)

# Stage 4: human approves -> planning gate ready.
st["issues"][0]["comments"].append({"body": "ACCEPTANCE-DECISION: Approved"})
step("S4 human approved -> gate planning->implementation", st)

# Stage 5: moved to implementation; sub-issues not yet created.
st["issues"][0]["labels"] = [{"name": "epic"}, {"name": "phase/implementation"}]
step("S5 phase/implementation, decomposition present, no children", st)

# Stage 6: sub-issues created with a dependency (102 depends on 101).
st["issues"] += [
    issue(101, "Parent epic: #100\nEmail/password auth", ["sub-task"]),
    issue(102, "Parent epic: #100\nOAuth flow\nDepends on: #101", ["sub-task"]),
]
step("S6 sub-issues #101,#102 (#102 blocked by #101)", st)

# Stage 7: children closed + DoD met -> impl gate ready.
for c in st["issues"][1:]:
    c["state"] = "closed"
    c["comments"] = [{"body": "REVIEW-VERDICT: APPROVE"}]
step("S7 sub-tasks closed + approved -> gate impl->testing", st)

# Stage 8: testing phase, no report yet. Carry the decomposition plan forward
# (the epic keeps its history as it advances through phases).
PLAN_C = "DECOMPOSITION-PLAN:\nSUB-TASK: email/password auth\nSUB-TASK: OAuth flow"
st["issues"] = [issue(100, epic_body, ["epic", "phase/testing"], comments=[PLAN_C])]
step("S8 phase/testing, no TEST-REPORT yet", st)

# Stage 9: tests fail -> route back to implementation + bugs.
st["issues"][0]["comments"] = [{"body": PLAN_C}, {"body": "TEST-REPORT: Fail (details: OAuth callback 500s)"}]
step("S9 TEST-REPORT: Fail -> rework to implementation", st)

# Stage 10: re-tested pass -> gate to acceptance.
st["issues"][0]["comments"] = [
    {"body": PLAN_C},
    {"body": "TEST-REPORT: Fail (oauth)"},
    {"body": "TEST-REPORT: Pass (oauth fixed, all green)"},
]
step("S10 TEST-REPORT: Pass -> gate testing->acceptance", st)

# Stage 11: acceptance phase, no approval request -> request it.
st["issues"] = [issue(100, epic_body, ["epic", "phase/acceptance"],
                      comments=[PLAN_C, "TEST-REPORT: Pass"])]
step("S11 phase/acceptance, request human sign-off", st)

# Stage 12: human blocks -> rework.
st["issues"][0]["comments"] = [
    {"body": PLAN_C},
    {"body": "REQUEST-APPROVAL-FROM: @product-owner"},
    {"body": "ACCEPTANCE-DECISION: Blocked (reason: password reset flow missing)"},
]
step("S12 human BLOCKED -> rework routes back", st)

# Stage 13: reworked + re-approved -> gate to done.
st["issues"][0]["comments"] = [
    {"body": PLAN_C},
    {"body": "ACCEPTANCE-DECISION: Blocked (reason: password reset missing)"},
    {"body": "PHASE-CHANGE: phase/acceptance -> phase/implementation (rework)"},
    {"body": "ACCEPTANCE-DECISION: Approved"},
]
step("S13 reworked + re-approved -> gate acceptance->done", st)

# Stage 14: done -> terminal.
st["issues"][0]["labels"] = [{"name": "epic"}, {"name": "phase/done"}]
step("S14 phase/done (terminal)", st)

print("="*70)
print("STEP TABLE")
print("="*70)
for i, (label, persona, action, target, _) in enumerate(LOG):
    tnum = target.get("number") if isinstance(target, dict) else target
    print(f"{i:2d}. {action:24s} {persona:20s} -> {tnum}")
json.dump(LOG, open("/tmp/sim_log.json", "w"), indent=2, default=str)
