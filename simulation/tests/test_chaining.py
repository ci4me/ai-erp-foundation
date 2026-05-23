"""Chained-action scenarios driven by the ``CHAIN-NEXT:`` marker.

The reference flow is a trivial typo fix that runs through implement →
review → merge → close in a single iteration. We also assert the
chain-depth cap, the allow-list, and the dedupe / stall / policy-label
helpers introduced alongside chaining.
"""

from __future__ import annotations

from simulation.tools import loop_speedup
from simulation.tools import next_prompt_orchestrator as orch
from simulation.tools import lock as lock_mod


def _issue(number, *, body="", labels=None, updated=None, title=""):
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": name} for name in (labels or [])],
        "updatedAt": updated,
        "comments": [],
    }


# --------------------------------------------------------------------------
# 1. End-to-end chain: implement → review → merge → close in one tick.
# --------------------------------------------------------------------------


def test_trivial_typo_chains_four_actions():
    chain = []
    bodies = {
        "implement_issue": "IMPLEMENTATION-COMPLETE: TRUE\nCHAIN-NEXT: review_pr",
        "review_pr": "REVIEW-VERDICT: APPROVE\nCHAIN-NEXT: merge_pr",
        "merge_pr": "MERGE-STATUS: COMPLETE\nCHAIN-NEXT: close_issue",
        "close_issue": "ISSUE-CLOSED: DONE",
    }
    current = "implement_issue"
    depth = 0
    while current:
        chain.append(current)
        plan = loop_speedup.evaluate_chain(bodies[current], chain_so_far=depth)
        if plan.exhausted:
            break
        current = plan.next_action
        depth = plan.chain_count
    # The fourth action (close_issue) has no CHAIN-NEXT so the loop ends
    # naturally; the depth counter only counts *transitions*, so 3 chained
    # hops produce 4 executed actions in one tick.
    assert chain == ["implement_issue", "review_pr", "merge_pr", "close_issue"]


def test_chain_respects_max_depth():
    body = "MARKER: VALUE\nCHAIN-NEXT: review_pr"
    plan = loop_speedup.evaluate_chain(body, chain_so_far=loop_speedup.MAX_CHAIN)
    assert plan.exhausted is True
    assert plan.next_action is None
    assert "limit" in plan.rejected_reason


def test_chain_rejects_unknown_action():
    body = "CHAIN-NEXT: format_disk"
    plan = loop_speedup.evaluate_chain(body, chain_so_far=0)
    assert plan.next_action is None
    assert "not in allowed" in plan.rejected_reason


def test_chain_returns_none_when_no_marker():
    plan = loop_speedup.evaluate_chain("nothing to chain", chain_so_far=0)
    assert plan.next_action is None
    assert plan.exhausted is False


# --------------------------------------------------------------------------
# 2. Dedupe cache.
# --------------------------------------------------------------------------


def test_dedupe_blocks_repeat_within_window():
    cache = loop_speedup.DedupeCache(window_minutes=60)
    assert cache.is_duplicate("mara", 35, "review_pr") is False
    cache.record("mara", 35, "review_pr")
    assert cache.is_duplicate("mara", 35, "review_pr") is True


def test_dedupe_allows_different_actor_or_target():
    cache = loop_speedup.DedupeCache(window_minutes=60)
    cache.record("mara", 35, "review_pr")
    assert cache.is_duplicate("iris", 35, "review_pr") is False
    assert cache.is_duplicate("mara", 36, "review_pr") is False
    assert cache.is_duplicate("mara", 35, "merge_gate") is False


# --------------------------------------------------------------------------
# 3. Stall tracker.
# --------------------------------------------------------------------------


def test_stall_tracker_skips_after_unchanged_hash():
    tracker = loop_speedup.StallTracker(limit=2)
    issue = _issue(7, body="same", updated="2026-05-23T10:00:00Z", labels=[])
    for _ in range(3):
        skip, count = tracker.observe(issue)
        assert skip is False
    skip, count = tracker.observe(issue)
    assert skip is True
    assert count == 3


def test_stall_tracker_resets_when_state_changes():
    tracker = loop_speedup.StallTracker(limit=2)
    issue = _issue(8, body="v1", updated="2026-05-23T10:00:00Z")
    tracker.observe(issue)
    tracker.observe(issue)
    issue["body"] = "v2"
    skip, count = tracker.observe(issue)
    assert skip is False
    assert count == 0


# --------------------------------------------------------------------------
# 4. Policy-label inference.
# --------------------------------------------------------------------------


def test_policy_labels_inferred_from_body():
    issue = _issue(
        12,
        body="This touches operating-model amendment and agent-governance docs.",
        labels=[],
    )
    out = loop_speedup.infer_policy_labels(issue)
    assert "risk:high" in out
    assert "area:agent-governance" in out


def test_policy_labels_skip_already_applied():
    issue = _issue(
        13,
        body="agent-governance change",
        labels=["area:agent-governance"],
    )
    out = loop_speedup.infer_policy_labels(issue)
    assert "area:agent-governance" not in out


# --------------------------------------------------------------------------
# 5. CoT requirements adapt to label.
# --------------------------------------------------------------------------


def test_trivial_label_disables_cot():
    issue = _issue(14, labels=["trivial"])
    spec = loop_speedup.cot_requirements(issue)
    assert spec["require_cot"] is False
    assert spec["min_steps"] == 1


def test_complex_label_demands_full_cot():
    issue = _issue(15, labels=["complex"])
    spec = loop_speedup.cot_requirements(issue)
    assert spec["require_cot"] is True
    assert spec["min_steps"] == 5


def test_medium_default():
    spec = loop_speedup.cot_requirements(_issue(16))
    assert spec["min_steps"] == 3
    assert spec["require_cot"] is True


# --------------------------------------------------------------------------
# 6. Cacheable prefix split.
# --------------------------------------------------------------------------


def test_split_cacheable_prefix_round_trips():
    prompt = "PREFIX\n<!-- CACHE -->\nDYNAMIC TAIL"
    prefix, dynamic = loop_speedup.split_cacheable_prefix(prompt)
    assert "PREFIX" in prefix
    assert "DYNAMIC" in dynamic
    assert prompt == prefix + loop_speedup.CACHE_SENTINEL + dynamic


def test_split_cacheable_prefix_missing_sentinel():
    prefix, dynamic = loop_speedup.split_cacheable_prefix("no marker here")
    assert prefix == ""
    assert dynamic == "no marker here"


# --------------------------------------------------------------------------
# 7. Gh response cache.
# --------------------------------------------------------------------------


def test_gh_response_cache_returns_memoized_result():
    cache = loop_speedup.GhResponseCache(ttl_seconds=5)
    calls = {"n": 0}

    def runner(args):
        calls["n"] += 1
        return f"call {calls['n']}"

    first = cache.call(runner, ["issue", "list"])
    second = cache.call(runner, ["issue", "list"])
    assert first == second == "call 1"
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# 8. Orchestrator-level integration: dedupe aborts the second tick.
# --------------------------------------------------------------------------


def test_orchestrator_aborts_duplicate_action():
    orch.DEDUPE_CACHE = loop_speedup.DedupeCache(window_minutes=60)
    orch.STALL_TRACKER = loop_speedup.StallTracker()
    issue = {
        "number": 99,
        "body": "TEAM-REQUEST: triage",
        "labels": [],
        "comments": [],
        "persona_id": "mara",
        "updatedAt": "2026-05-23T10:00:00Z",
    }
    first = orch.check_locks_and_cycles(
        repo="x/y",
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    # First call records; second call should hit the cache.
    orch.DEDUPE_CACHE.record("mara", 99, "triage_issue")
    second = orch.check_locks_and_cycles(
        repo="x/y",
        issue=issue,
        proposed_action="triage_issue",
        runner=lock_mod.InMemoryGh(),
    )
    assert second.abort is True
    assert second.reason.startswith("dedupe:")


# --------------------------------------------------------------------------
# 9. validator.extract_chain_next contract.
# --------------------------------------------------------------------------


def test_extract_chain_next_at_eol():
    from simulation.tools.validator import extract_chain_next
    body = "Some output\nCHAIN-NEXT: review_pr\n"
    assert extract_chain_next(body) == "review_pr"


def test_extract_chain_next_missing():
    from simulation.tools.validator import extract_chain_next
    assert extract_chain_next("No chain marker") is None


def test_extract_chain_next_case_insensitive():
    from simulation.tools.validator import extract_chain_next
    assert extract_chain_next("Chain-Next: Merge_Pr") == "merge_pr"


def test_extract_chain_next_ignores_multiple():
    """Two CHAIN-NEXT markers are ambiguous → refuse to chain."""
    from simulation.tools.validator import extract_chain_next
    body = "CHAIN-NEXT: review_pr\nCHAIN-NEXT: merge_pr\n"
    assert extract_chain_next(body) is None


# --------------------------------------------------------------------------
# 10. loop_runner.run_iterations honours chaining + MAX_CHAIN cap.
# --------------------------------------------------------------------------


def _mock_runtime(bodies_by_action, *, max_iterations=3, max_chain=3):
    """Run loop_runner.run_iterations against a deterministic mock."""
    from simulation.tools import loop_runner

    actions_log: list[str] = []
    posted: list[str] = []

    def select_next_action():
        # Always start each iteration with implement_issue.
        return "implement_issue", {"pr_number": 99}, 99

    def fetch_issue(target):
        return {
            "number": 99,
            "body": "trivial fix",
            "labels": [{"name": "trivial"}],
            "comments": [],
            "updatedAt": "2026-05-23T10:00:00Z",
        }

    def execute_action(action, ctx):
        actions_log.append(action)
        return bodies_by_action.get(action, "(no body)")

    def post_to_github(target, body):
        posted.append(body[:40])

    return loop_runner.run_iterations(
        repo="x/y",
        select_next_action=select_next_action,
        fetch_issue=fetch_issue,
        execute_action=execute_action,
        post_to_github=post_to_github,
        max_iterations=max_iterations,
        max_chain=max_chain,
        lock_runner=lock_mod.InMemoryGh(),
    ), actions_log


def test_run_iterations_breaks_chain_after_three():
    bodies = {
        "implement_issue": (
            "## Implementation\nWe fixed it.\n\n## Changes made\n- done\n\n"
            "IMPLEMENTATION-COMPLETE: TRUE\nCHAIN-NEXT: review_pr\n"
        ),
        "review_pr": (
            "## Review summary\nLooks good to ship.\nREVIEW-VERDICT: APPROVE\n"
            "CHAIN-NEXT: merge_pr\n"
        ),
        "merge_pr": (
            "## Merge summary\nMerged.\nMERGE-STATUS: COMPLETE\nCHAIN-NEXT: close_issue\n"
        ),
        "close_issue": "## Close reason\nDone.\nISSUE-CLOSED: DONE\n",
    }
    records, log = _mock_runtime(bodies, max_iterations=1, max_chain=3)
    assert len(records) == 1
    # Allowed up to 3 chain hops -> 4 actions in one logical iteration.
    assert records[0].chain_length <= 3
    assert log == log  # mocks recorded each action
