#!/usr/bin/env python3
"""Drive the login-feature lifecycle as a **pure dry-run**, planner in the loop.

This is the offline, no-mutation walkthrough mandated by the login dry-run task.
Starting from the ``TEAM-REQUEST`` fixture built by ``build_login_fixture.py``,
it evolves an in-memory state snapshot one stage at a time. At each stage it:

  1. injects the comment / marker an AI persona or the human would post,
  2. writes the evolved fixture to ``/tmp/login_fixture_step<NN>.json``,
  3. re-runs the *real* planner — ``scripts/run_planner.py --fixture ... --mode
     multi`` — as a subprocess (DRY-RUN; never ``--apply``),
  4. appends the planner's full stdout to ``/tmp/login_simulation.log``, and
  5. records ``(step, action, persona, marker, phase)`` for the report.

Nothing here calls ``gh``, pushes a branch, opens an issue/PR, or touches a
remote. State is read only from the JSON fixtures this script writes locally.

The marker recorded for a stage is the one **posted to enter that stage** — the
signal an agent/human produced that the planner then reacts to.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

LOG_PATH = "/tmp/login_simulation.log"
STEP_TABLE_PATH = "/tmp/login_step_table.json"
RUN_PLANNER = os.path.join(_ROOT, "scripts", "run_planner.py")

STEP_TABLE: list[dict] = []


def _issue(n, body, labels, comments=(), state="open"):
    """Build an issue record in the shape the state analyzer expects."""
    return {
        "number": n,
        "title": f"#{n}",
        "body": body,
        "labels": [{"name": label} for label in labels],
        "comments": [{"body": c, "createdAt": "2026-05-29T02:00:00Z"} for c in comments],
        "state": state,
        "createdAt": "2026-05-29T00:00:00Z",
    }


def _phase_of(state) -> str:
    for issue in state["issues"]:
        for label in issue.get("labels", []):
            if label["name"].startswith("phase/"):
                return label["name"]
    return "—"


def run_stage(step_no, label, state, marker_posted):
    """Write the fixture, run the real planner, capture output, record the row."""
    fixture_path = f"/tmp/login_fixture_step{step_no:02d}.json"
    with open(fixture_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)

    proc = subprocess.run(
        [sys.executable, RUN_PLANNER, "--fixture", fixture_path, "--mode", "multi"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    output = proc.stdout + (proc.stderr or "")

    # Parse the planner's chosen top action + persona out of its own output.
    persona, action = "—", "(human wait / terminal)"
    for line in output.splitlines():
        if "| ok" in line and "plan_built" not in line and "[dry]" in line:
            # e.g. "📝 [dry] ari-orchestrator | create_issue | discussion#1 | ok"
            parts = [p.strip() for p in line.split("|")]
            persona = parts[0].split("]")[-1].strip()
            action = parts[1].strip()
    if "No problems detected" in output:
        action = "(no action — terminal / human wait)"
        persona = "—"

    phase = _phase_of(state)
    row = {
        "step": step_no,
        "label": label,
        "marker_posted": marker_posted,
        "persona": persona,
        "next_action": action,
        "phase": phase,
    }
    STEP_TABLE.append(row)

    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write("=" * 78 + "\n")
        fh.write(f"STEP {step_no:02d}: {label}\n")
        fh.write(f"  marker posted to enter this stage: {marker_posted}\n")
        fh.write(f"  fixture: {fixture_path}\n")
        fh.write("-" * 78 + "\n")
        fh.write(output)
        fh.write(f"\n>> RECORDED: phase={phase} persona={persona} next_action={action}\n\n")

    print(f"S{step_no:02d} {label}")
    print(f"    phase={phase} | marker={marker_posted}")
    print(f"    NEXT: {persona} | {action}\n")


def main() -> int:
    # Fresh log each run.
    open(LOG_PATH, "w").close()

    EPIC_BODY = (
        "TEAM-REQUEST: Add a login feature (email/password + OAuth).\n"
        "From discussion #1"
    )
    PLAN_C = ("DECOMPOSITION-PLAN:\n"
              "SUB-TASK: email/password auth\n"
              "SUB-TASK: OAuth flow\n"
              "SUB-TASK: session store")

    disc = {
        "number": 1,
        "title": "Add a login feature",
        "body": "TEAM-REQUEST: Add a login feature (email/password + OAuth) to my app.",
        "comments": [],
        "createdAt": "2026-05-29T00:00:00Z",
    }

    print("=" * 70)
    print("LOGIN-FEATURE DRY-RUN SIMULATION (planner in the loop, no mutations)")
    print("=" * 70 + "\n")

    # S0: fresh TEAM-REQUEST discussion only.
    st = {"repo": "ci4me/ai-erp-foundation", "prs": [], "issues": [], "discussions": [disc]}
    run_stage(0, "fresh TEAM-REQUEST discussion #1", st, "TEAM-REQUEST:")

    # S1: issue #100 opened from the request and triaged as an epic in planning.
    st["issues"] = [_issue(100, EPIC_BODY, ["epic", "phase/planning"])]
    run_stage(1, "issue #100 opened + triaged (epic, phase/planning)", st, "EPIC (triage label)")

    # S2: design debate underway (recent => within timeout, no resolution yet).
    st["issues"][0]["comments"] = [
        {"body": "ARGUMENT: use bcrypt + short-lived JWT sessions.",
         "createdAt": "2026-05-29T01:00:00Z"},
        {"body": "COUNTER-PROPOSAL: server-side sessions over JWT.",
         "createdAt": "2026-05-29T01:05:00Z"},
    ]
    run_stage(2, "design debate active (within timeout)", st, "ARGUMENT: / COUNTER-PROPOSAL:")

    # S3: consensus + decomposition plan + approval requested (awaiting human).
    st["issues"][0]["comments"] += [
        {"body": "CONSENSUS-REACHED: bcrypt + server-side sessions + OAuth via provider SDK "
                 "(signees: @theo-architect, @iris-security)",
         "createdAt": "2026-05-29T01:30:00Z"},
        {"body": PLAN_C, "createdAt": "2026-05-29T01:31:00Z"},
        {"body": "REQUEST-APPROVAL-FROM: @product-owner", "createdAt": "2026-05-29T01:32:00Z"},
    ]
    run_stage(3, "consensus + decomposition plan + approval requested", st, "CONSENSUS-REACHED: / REQUEST-APPROVAL-FROM:")

    # S4: human approves -> planning gate ready.
    st["issues"][0]["comments"].append(
        {"body": "ACCEPTANCE-DECISION: Approved", "createdAt": "2026-05-29T02:00:00Z"})
    run_stage(4, "human approved -> gate planning->implementation", st, "ACCEPTANCE-DECISION: Approved")

    # S5: moved to implementation; sub-issues not yet created.
    st["issues"][0]["labels"] = [{"name": "epic"}, {"name": "phase/implementation"}]
    run_stage(5, "phase/implementation, decomposition present, no children", st, "PHASE-CHANGE: planning->implementation")

    # S6: sub-issues created, one blocked by a dependency (#102 depends on #101).
    st["issues"] += [
        _issue(101, "Parent epic: #100\nEmail/password auth", ["sub-task", "phase/implementation"]),
        _issue(102, "Parent epic: #100\nOAuth flow\nDepends on: #101", ["sub-task", "phase/implementation"]),
    ]
    run_stage(6, "sub-issues #101,#102 created (#102 blocked by #101)", st, "SUB-TASK: (children created)")

    # S7: children closed + DoD met -> implementation gate ready.
    for child in st["issues"][1:]:
        child["state"] = "closed"
        child["comments"] = [{"body": "REVIEW-VERDICT: APPROVE", "createdAt": "2026-05-29T03:00:00Z"}]
    run_stage(7, "sub-tasks closed + approved -> gate impl->testing", st, "REVIEW-VERDICT: APPROVE")

    # S8: testing phase, no report yet (epic carries its plan history forward).
    st["issues"] = [_issue(100, EPIC_BODY, ["epic", "phase/testing"], comments=[PLAN_C])]
    run_stage(8, "phase/testing, no TEST-REPORT yet", st, "PHASE-CHANGE: implementation->testing")

    # S9: tests fail -> route back to implementation.
    st["issues"][0]["comments"] = [
        {"body": PLAN_C, "createdAt": "2026-05-29T02:00:00Z"},
        {"body": "TEST-REPORT: Fail (details: OAuth callback 500s)", "createdAt": "2026-05-29T03:30:00Z"},
    ]
    run_stage(9, "TEST-REPORT: Fail -> rework to implementation", st, "TEST-REPORT: Fail")

    # S10: re-tested pass -> gate to acceptance.
    st["issues"][0]["comments"].append(
        {"body": "TEST-REPORT: Pass (oauth fixed, all green)", "createdAt": "2026-05-29T04:00:00Z"})
    run_stage(10, "TEST-REPORT: Pass -> gate testing->acceptance", st, "TEST-REPORT: Pass")

    # S11: acceptance phase, no approval request yet -> request human sign-off.
    st["issues"] = [_issue(100, EPIC_BODY, ["epic", "phase/acceptance"], comments=[PLAN_C, "TEST-REPORT: Pass"])]
    run_stage(11, "phase/acceptance, request human sign-off", st, "PHASE-CHANGE: testing->acceptance")

    # S12: human blocks -> rework routes back.
    st["issues"][0]["comments"] = [
        {"body": PLAN_C, "createdAt": "2026-05-29T02:00:00Z"},
        {"body": "REQUEST-APPROVAL-FROM: @product-owner", "createdAt": "2026-05-29T04:30:00Z"},
        {"body": "ACCEPTANCE-DECISION: Blocked (reason: password reset flow missing)",
         "createdAt": "2026-05-29T05:00:00Z"},
    ]
    run_stage(12, "human BLOCKED -> rework routes back", st, "ACCEPTANCE-DECISION: Blocked")

    # S13: reworked + re-approved -> gate to done.
    st["issues"][0]["comments"] += [
        {"body": "PHASE-CHANGE: phase/acceptance -> phase/implementation (rework)",
         "createdAt": "2026-05-29T05:30:00Z"},
        {"body": "ACCEPTANCE-DECISION: Approved", "createdAt": "2026-05-29T06:00:00Z"},
    ]
    run_stage(13, "reworked + re-approved -> gate acceptance->done", st, "ACCEPTANCE-DECISION: Approved")

    # S14: done -> terminal (no further action).
    st["issues"][0]["labels"] = [{"name": "epic"}, {"name": "phase/done"}]
    run_stage(14, "phase/done (terminal)", st, "PHASE-CHANGE: acceptance->done")

    with open(STEP_TABLE_PATH, "w", encoding="utf-8") as fh:
        json.dump(STEP_TABLE, fh, indent=2)

    print("=" * 70)
    print(f"{len(STEP_TABLE)} stages simulated. Full planner output: {LOG_PATH}")
    print(f"Step table: {STEP_TABLE_PATH}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
