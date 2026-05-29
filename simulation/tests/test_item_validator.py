"""Tests for the validity / scope filter (item_validator).

Plain asserts so the module runs under pytest or a bare harness.
"""

from simulation.tools.item_validator import FOCUS_LABEL, filter_state, validate_item
from simulation.tools.state_analyzer import analyze_state


def _issue(n, *, labels=(), body="", files=None):
    item = {"number": n, "title": f"#{n}", "body": body,
            "labels": [{"name": x} for x in labels], "comments": []}
    if files is not None:
        item["files"] = [{"path": p} for p in files]
    return item


def test_skip_label_is_dropped():
    ok, reason = validate_item(_issue(1, labels=["duplicate"]), "issue")
    assert not ok and "duplicate" in reason


def test_clean_item_is_kept():
    ok, _ = validate_item(_issue(2, labels=["ready-for-agent"]), "issue")
    assert ok


def test_note_only_pr_skipped():
    ok, reason = validate_item(_issue(3, files=["NOTES.md", "README.md"]), "pr")
    assert not ok and "note-only" in reason


def test_pr_with_code_kept():
    ok, _ = validate_item(_issue(4, files=["src/Auth.php", "NOTES.md"]), "pr")
    assert ok


def test_pr_without_file_info_left_in_scope():
    # Unknown files -> don't guess, keep it.
    ok, _ = validate_item(_issue(5), "pr")
    assert ok


def test_filter_drops_skip_labeled():
    state = {"prs": [], "discussions": [],
             "issues": [_issue(1, labels=["wontfix"]), _issue(2, labels=["ready-for-agent"])]}
    filtered, skipped = filter_state(state)
    nums = [i["number"] for i in filtered["issues"]]
    assert nums == [2]
    assert any(s[1] == 1 for s in skipped)


def test_focus_mode_restricts_to_active():
    state = {
        "prs": [_issue(10, files=["a.py"])],
        "discussions": [],
        "issues": [
            _issue(1, labels=["ready-for-agent"]),
            _issue(2, labels=[FOCUS_LABEL]),
        ],
    }
    filtered, skipped = filter_state(state)
    assert [i["number"] for i in filtered["issues"]] == [2]
    assert filtered["prs"] == []  # PR not in focus set
    assert {s[1] for s in skipped} == {1, 10}


def test_no_labels_is_noop():
    state = {"prs": [], "discussions": [],
             "issues": [_issue(1), _issue(2)]}
    filtered, skipped = filter_state(state)
    assert len(filtered["issues"]) == 2 and skipped == []


def test_analyze_state_respects_focus():
    # An out-of-focus issue with a request marker must NOT produce a problem;
    # the focused one still does.
    state = {
        "prs": [], "discussions": [],
        "issues": [
            _issue(1, body="REQUEST-REPLY-FROM: @mara-product-owner"),
            _issue(2, labels=[FOCUS_LABEL], body="REQUEST-REPLY-FROM: @mara-product-owner"),
        ],
    }
    targets = {p["target"]["number"] for p in analyze_state(state)}
    assert 2 in targets and 1 not in targets
