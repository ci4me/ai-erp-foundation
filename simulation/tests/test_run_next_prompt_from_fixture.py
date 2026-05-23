import json
from pathlib import Path

from simulation.tools import run_next_prompt_from_fixture


def test_fixture_runner_replays_open_pr(tmp_path):
    fixture = {
        "pr": {
            "number": 35,
            "title": "feat: test",
            "body": "## Required reviews\n- Mara (Product)\n",
            "reviewDecision": "REVIEW_REQUIRED",
            "labels": [{"name": "area:docs"}],
            "author": {"login": "ci4me"},
            "headRefName": "feature",
            "baseRefName": "main",
            "url": "https://example.test/pr/35",
            "comments": [],
            "reviews": [],
            "files": [{"path": "docs/example.md"}],
        },
        "issues": [],
        "discussions": [],
        "milestones": [],
        "diff": "diff --git a/docs/example.md b/docs/example.md\n@@ -0,0 +1 @@\n+hello\n",
    }
    fixture_path = tmp_path / "state.json"
    output_path = tmp_path / "next.md"
    fixture_path.write_text(json.dumps(fixture))

    rc = run_next_prompt_from_fixture.run_from_fixture(
        fixture_path,
        repo="ci4me/ai-erp-foundation",
        output=output_path,
        probe_only=False,
        max_diff_chars=2000,
        post_mode="dry-run",
    )

    assert rc == 0
    rendered = output_path.read_text()
    assert "Action: Review PR #35" in rendered
    assert "mara-product-owner" in rendered
