import json

from simulation.tools import agent_output_validator, next_prompt


def _valid_iris_review() -> str:
    return """---
Persona: Iris
Role: AI Security Reviewer
Layer: assurance
Model: claude-sonnet-4-6
Source: PR #35 diff
Self-review conflict: Yes
Run-ID: 2026-05-23T06:00:00Z-iris-review-pr35
---

REVIEW-VERDICT: APPROVE_WITH_CONDITIONS

**Verdict:** APPROVE_WITH_CONDITIONS

**Acceptance matrix:**
| Criterion | Status | Evidence (path:line or MISSING) |
| --- | --- | --- |
| Workflow permissions are explicit | PASS | .github/workflows/idea-lab.yml:3 |

**Blocking findings:**
1. none

**Non-blocking findings:**
1. Keep the live dispatch behind budget gates.

**Required next action:** Run next_prompt.py again.
"""


def test_loop_progresses_to_next_reviewer_after_valid_marker(monkeypatch):
    pr = {
        "number": 35,
        "title": "feat(brainstorm): Nova Idea Lab autonomous loop",
        "body": """Adds Nova Idea Lab workflow.

## Required reviews
- Iris (Security) - workflow permissions
- Mara (Product) - product fit
""",
        "reviewDecision": "",
        "labels": [
            {"name": "risk:high"},
            {"name": "area:ci"},
            {"name": "area:agent-governance"},
        ],
        "author": {"login": "ci4me"},
        "headRefName": "feat/brainstorm-mechanism-nova",
        "baseRefName": "main",
        "comments": [],
        "reviews": [],
        "files": [
            {"path": ".github/workflows/idea-lab.yml"},
            {"path": ".github/agent-prompts/nova-idea-generator.md"},
        ],
        "url": "https://github.com/ci4me/ai-erp-foundation/pull/35",
    }

    def fake_gh(args, repo):
        if args[:2] == ["pr", "list"]:
            return json.dumps([pr])
        if args[:2] == ["issue", "list"]:
            return "[]"
        if args[:1] == ["api"] and len(args) > 1 and "milestones" in args[1]:
            return "[]"
        if args[:2] == ["api", "graphql"]:
            return json.dumps({"data": {"repository": {"discussions": {"nodes": []}}}})
        if args[:2] == ["pr", "view"]:
            return json.dumps(pr)
        raise AssertionError(args)

    monkeypatch.setattr(next_prompt, "_gh", fake_gh)

    priority, context = next_prompt.resolve_priority(
        next_prompt.gather_repo_state("ci4me/ai-erp-foundation"),
        "ci4me/ai-erp-foundation",
    )
    assert priority == "review_pr"
    assert context["persona_id"] == "iris-security"

    body = _valid_iris_review()
    validation = agent_output_validator.validate_agent_output(
        body,
        action="review_pr",
        persona_id="iris-security",
    )
    assert validation.valid, validation.errors

    pr["comments"].append(
        {
            "body": body,
            "author": {"login": "agent-iris"},
            "createdAt": "2026-05-23T06:00:00Z",
            "url": "https://example.test/pr/35#iris",
        }
    )

    priority, context = next_prompt.resolve_priority(
        next_prompt.gather_repo_state("ci4me/ai-erp-foundation"),
        "ci4me/ai-erp-foundation",
    )
    assert priority == "review_pr"
    assert context["posted_reviewers"] == ["iris-security"]
    assert context["persona_id"] == "mara-product-owner"
