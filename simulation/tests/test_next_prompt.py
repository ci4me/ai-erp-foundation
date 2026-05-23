from simulation.tools import next_prompt


def test_parse_required_reviewers_from_pr_body():
    personas = next_prompt._load_persona_index()
    aliases = next_prompt._persona_aliases(personas)
    body = """
## Required reviews
- Theo (Architect) - architecture
- Vera (Risk) - risk classification
- Mara (Product) - product fit
- Iris (Security) - permissions
- Sim-Human - maintainer sign-off
"""

    reviewers = next_prompt._parse_required_reviewers(body, aliases)

    assert reviewers[:4] == [
        "theo-architect",
        "vera-risk-officer",
        "mara-product-owner",
        "iris-security",
    ]
    assert "sim-human" not in reviewers


def test_review_history_extracts_persona_headers_and_verdicts():
    personas = next_prompt._load_persona_index()
    aliases = next_prompt._persona_aliases(personas)
    pr = {
        "comments": [
            {
                "body": """---
Persona: theo-architect
Role: AI CQRS/DDD Architect
---

## Verdict: APPROVE
""",
                "author": {"login": "ci4me"},
                "createdAt": "2026-05-23T00:00:00Z",
                "url": "https://example.test/theo",
            },
            {
                "body": "**⚖️ Vera (Risk)**\n\n**Verdict: APPROVE_WITH_CONDITIONS**",
                "author": {"login": "ci4me"},
                "createdAt": "2026-05-23T00:01:00Z",
                "url": "https://example.test/vera",
            },
            {
                "body": "**🚦 Rhea (Release Manager)**\n\n**Final verdict: BLOCKED**",
                "author": {"login": "ci4me"},
                "createdAt": "2026-05-23T00:02:00Z",
                "url": "https://example.test/rhea",
            },
        ],
        "reviews": [],
    }

    posted, history = next_prompt._review_history(pr, aliases)

    assert posted == ["theo-architect", "vera-risk-officer", "rhea-release-manager"]
    assert [item["verdict"] for item in history] == [
        "APPROVE",
        "APPROVE_WITH_CONDITIONS",
        "BLOCKED",
    ]


def test_template_renderer_requires_all_variables():
    try:
        next_prompt._render_template("Hello {{ name }} from {{ missing }}", {"name": "Mara"})
    except RuntimeError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("missing template variable did not fail")


def test_action_catalog_templates_exist_and_persona_actions_are_valid():
    actions = next_prompt._load_action_catalog()
    action_ids = {str(action["id"]) for action in actions}
    assert action_ids, "action catalog must not be empty"

    for action in actions:
        template = next_prompt.ACTION_TEMPLATES_DIR / str(action["template"])
        assert template.exists(), f"catalog action {action['id']} points to missing template {template}"

    personas = next_prompt._load_persona_index()
    assert personas, "persona prompts must be discoverable"
    for persona_id, doc in personas.items():
        for relation in ("primary", "support"):
            for action_id in next_prompt._persona_action_ids(doc, relation):
                assert action_id in action_ids, f"{persona_id} declares unknown {relation} action {action_id}"

    missing_primary = [
        action_id
        for action_id in action_ids
        if not next_prompt._personas_for_action(action_id, "primary", personas)
    ]
    assert missing_primary == [], f"every catalog action needs at least one primary persona: {missing_primary}"


def test_operating_model_policy_adds_required_reviewers():
    changed = [".github/action-templates/review-pr.md", "simulation/tools/next_prompt.py"]
    reviewers = next_prompt._policy_required_reviewers(changed)

    assert "theo-architect" in reviewers
    assert "vera-risk-officer" in reviewers
    assert "rhea-release-manager" in reviewers
    assert "prism-promptops" in reviewers
    assert "tessa-test-lead" in reviewers


def test_terminal_discussion_is_not_selected_for_comment():
    personas = next_prompt._load_persona_index()
    state = next_prompt.RepoState(
        open_prs=[],
        open_issues=[],
        open_discussions=[
            {
                "id": "D_terminal",
                "number": 10,
                "title": "Idea Lab: already done",
                "body": "DISCUSSION-STATE: RESOLVED\nNo more agent comments needed.",
                "category": {"name": "Idea Lab"},
                "comments": {"nodes": []},
            }
        ],
        open_milestones=[],
        existing_personas=set(personas),
        existing_scenarios=set(next_prompt._scenario_catalog()),
        prs_with_changes_requested=[],
    )

    assert next_prompt._find_discussion_to_comment(state, personas) is None


def test_discussion_marker_can_request_specific_persona():
    personas = next_prompt._load_persona_index()
    state = next_prompt.RepoState(
        open_prs=[],
        open_issues=[],
        open_discussions=[
            {
                "id": "D_needs_iris",
                "number": 11,
                "title": "Security question",
                "body": "NEEDS-PERSONA: Iris\nCan this workflow dispatch be abused?",
                "category": {"name": "Architecture"},
                "comments": {"nodes": []},
            }
        ],
        open_milestones=[],
        existing_personas=set(personas),
        existing_scenarios=set(next_prompt._scenario_catalog()),
        prs_with_changes_requested=[],
    )

    selected = next_prompt._find_discussion_to_comment(state, personas)

    assert selected is not None
    assert selected["persona_id"] == "iris-security"
    assert selected["lifecycle_state"] == "NEEDS_COMMENT"


def test_discussion_variables_use_graphql_id_field():
    values = next_prompt._discussion_variables(
        {
            "discussion": {
                "id": "D_graphql_node_id",
                "number": 12,
                "title": "Idea Lab: sample",
                "body": "NEEDS-COMMENT: Mara",
                "url": "https://example.test/discussions/12",
                "category": {"name": "Idea Lab"},
                "comments": {"nodes": []},
                "persona_id": "mara-product-owner",
            }
        }
    )

    assert values["discussion_node_id"] == "D_graphql_node_id"
    assert values["persona_id"] == "mara-product-owner"


def test_comment_discussion_prompt_renders_without_unresolved_template_tokens():
    personas = next_prompt._load_persona_index()
    state = next_prompt.RepoState(
        open_prs=[],
        open_issues=[],
        open_discussions=[],
        open_milestones=[],
        existing_personas=set(personas),
        existing_scenarios=set(next_prompt._scenario_catalog()),
        prs_with_changes_requested=[],
    )
    context = {
        "discussion": {
            "id": "D_render",
            "number": 13,
            "title": "Idea Lab: render test",
            "body": "NEEDS-COMMENT: Mara\nShould this become an issue?",
            "url": "https://example.test/discussions/13",
            "category": {"name": "Idea Lab"},
            "comments": {"nodes": []},
            "persona_id": "mara-product-owner",
            "lifecycle_state": "NEEDS_COMMENT",
            "needs_comment_reason": "test marker",
        }
    }

    prompt = next_prompt.render_prompt(
        "ci4me/ai-erp-foundation",
        "comment_discussion",
        context,
        state,
        post_mode="dry-run",
    )

    assert "{{" not in prompt
    assert "}}" not in prompt
    assert "## DO NOTs for this action" in prompt
    assert "DISCUSSION-STATE:" in prompt
    assert "discussion comment validation passed" in prompt


def _complete_state(*, pr=None, issue=None, milestone=None):
    personas = next_prompt._load_persona_index()
    return next_prompt.RepoState(
        open_prs=[pr] if pr else [],
        open_issues=[issue] if issue else [],
        open_discussions=[],
        open_milestones=[milestone] if milestone else [],
        existing_personas=set(next_prompt._persona_catalog()),
        existing_scenarios=set(next_prompt._scenario_catalog()),
        prs_with_changes_requested=[],
    )


def test_accept_pr_selected_when_all_reviews_done(monkeypatch):
    pr = {
        "number": 101,
        "title": "Ready PR",
        "body": "## Required reviews\n- Theo (Architect)\n",
        "labels": [],
        "reviewDecision": "",
        "files": [],
        "comments": [
            {
                "body": "---\nPersona: theo-architect\n---\n\n## Verdict: APPROVE",
                "author": {"login": "ci4me"},
                "createdAt": "2026-05-23T00:00:00Z",
                "url": "https://example.test/theo",
            }
        ],
        "reviews": [],
    }
    monkeypatch.setattr(next_prompt, "_load_pr_details", lambda repo, number: dict(pr))

    priority, context = next_prompt.resolve_priority(_complete_state(pr=pr), "ci4me/ai-erp-foundation")

    assert priority == "accept_pr"
    assert context["persona_id"] == "rhea-release-manager"


def test_merge_pr_selected_after_acceptance_marker(monkeypatch):
    pr = {
        "number": 102,
        "title": "Accepted PR",
        "body": "## Required reviews\n- Theo (Architect)\n",
        "labels": [],
        "reviewDecision": "",
        "files": [],
        "comments": [
            {"body": "---\nPersona: theo-architect\n---\n\n## Verdict: APPROVE", "author": {"login": "ci4me"}},
            {"body": "ACCEPTANCE-DECISION: ACCEPT PR#102 -- ready", "author": {"login": "ci4me"}},
        ],
        "reviews": [],
    }
    monkeypatch.setattr(next_prompt, "_load_pr_details", lambda repo, number: dict(pr))

    priority, context = next_prompt.resolve_priority(_complete_state(pr=pr), "ci4me/ai-erp-foundation")

    assert priority == "merge_pr"
    assert context["persona_id"] == "rhea-release-manager"


def test_reject_pr_selected_after_reject_marker(monkeypatch):
    pr = {
        "number": 103,
        "title": "Rejected PR",
        "body": "",
        "labels": [],
        "reviewDecision": "",
        "files": [],
        "comments": [{"body": "ACCEPTANCE-DECISION: REJECT PR#103 -- superseded", "author": {"login": "ci4me"}}],
        "reviews": [],
    }
    monkeypatch.setattr(next_prompt, "_load_pr_details", lambda repo, number: dict(pr))

    priority, context = next_prompt.resolve_priority(_complete_state(pr=pr), "ci4me/ai-erp-foundation")

    assert priority == "reject_pr"
    assert context["persona_id"] == "rhea-release-manager"


def test_close_issue_selected_from_terminal_label():
    issue = {
        "number": 55,
        "title": "Done issue",
        "body": "Evidence is in merged PR.",
        "labels": [{"name": "ready-to-close"}],
        "milestone": None,
    }

    priority, context = next_prompt.resolve_priority(_complete_state(issue=issue), "ci4me/ai-erp-foundation")

    assert priority == "close_issue"
    assert context["issue"]["close_reason"] == "completed"


def test_close_milestone_selected_when_no_open_issues():
    milestone = {
        "number": 7,
        "title": "Phase 1",
        "state": "open",
        "open_issues": 0,
        "closed_issues": 3,
        "due_on": None,
    }

    priority, context = next_prompt.resolve_priority(_complete_state(milestone=milestone), "ci4me/ai-erp-foundation")

    assert priority == "close_milestone"
    assert context["milestone"]["persona_id"] == "rhea-release-manager"
