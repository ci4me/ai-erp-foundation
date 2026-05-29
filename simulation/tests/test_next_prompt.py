from simulation.tools import next_prompt, next_prompt_legacy


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


def test_policy_required_reviewers_for_operating_model_paths():
    changed = [
        ".github/agent-prompts/nova-idea-generator.md",
        ".github/workflows/idea-lab.yml",
        "docs/idea-lab.md",
    ]

    reviewers = next_prompt._policy_required_reviewers(changed)

    assert "theo-architect" in reviewers
    assert "vera-risk-officer" in reviewers
    assert "rhea-release-manager" in reviewers
    assert "prism-promptops" in reviewers
    assert "iris-security" in reviewers


def test_discussion_terminal_marker_prevents_more_comments():
    discussion = {
        "title": "Idea: something",
        "body": "Still open",
        "comments": {"nodes": [{"body": "DISCUSSION-STATE: PROMOTED\nPromoted to Issue #42"}]},
    }

    assert next_prompt._discussion_has_terminal_marker(discussion) is True


def test_discussion_variables_accept_graphql_id_as_node_id():
    context = {
        "discussion": {
            "id": "D_kwDOExample",
            "number": 7,
            "title": "Idea Lab: cache prompts",
            "body": "Body",
            "url": "https://example.test/discussions/7",
            "persona_id": "mara-product-owner",
        }
    }

    variables = next_prompt._discussion_variables(context)

    assert variables["discussion_node_id"] == "D_kwDOExample"
    assert variables["persona_id"] == "mara-product-owner"


def test_rendered_prompt_validation_ignores_github_actions_expressions():
    prompt = """# Autonomous loop - next iteration (review_pr)

## Hard Caps

### Step 1

Workflow expression: ${{ github.actor }}
"""

    assert next_prompt.validate_rendered_prompt(prompt) == []


def test_static_config_is_valid():
    assert next_prompt.validate_static_config() == []


def test_lifecycle_action_templates_are_cataloged():
    actions = {action["id"]: action for action in next_prompt._load_action_catalog()}
    required = {
        "accept_pr",
        "reject_pr",
        "open_issue",
        "close_issue",
        "reopen_issue",
        "create_milestone",
        "assign_milestone",
        "close_milestone",
        "merge_pr",
        "request_review",
    }
    assert required <= set(actions)
    for action_id in required:
        template = next_prompt.ACTION_TEMPLATES_DIR / actions[action_id]["template"]
        assert template.exists(), action_id


def test_closable_issue_selector_uses_terminal_labels():
    state = next_prompt.RepoState(
        open_prs=[],
        open_issues=[
            {"number": 9, "title": "done", "labels": [{"name": "state:accepted"}], "milestone": {"title": "M1"}},
        ],
        open_discussions=[],
        existing_personas=set(),
        existing_scenarios=set(),
        prs_with_changes_requested=[],
    )

    issue = next_prompt._find_closable_issue(state)

    assert issue is not None
    assert issue["number"] == 9


def test_milestone_selector_closes_zero_open_issue_milestone():
    state = next_prompt.RepoState(
        open_prs=[],
        open_issues=[],
        open_discussions=[],
        existing_personas=set(),
        existing_scenarios=set(),
        prs_with_changes_requested=[],
        open_milestones=[{"number": 2, "title": "M1", "open_issues": 0, "closed_issues": 3}],
    )

    milestone = next_prompt._find_closable_milestone(state)

    assert milestone is not None
    assert milestone["number"] == 2


def test_merge_ready_marker_detection():
    text = "Persona: Rhea\n\nACCEPTANCE-DECISION: ACCEPT\nRHEA-VERDICT: APPROVE"

    assert next_prompt._has_any_marker(text, ["ACCEPTANCE-DECISION: ACCEPT"])


def test_extract_verdict_accepts_marker_and_bold_label_styles():
    marker_body = "REVIEW-VERDICT: APPROVE_WITH_CONDITIONS\n\n**Verdict:** APPROVE_WITH_CONDITIONS"
    bold_label_body = "**Verdict:** APPROVE_WITH_CONDITIONS"

    assert next_prompt._extract_verdict(marker_body) == "APPROVE_WITH_CONDITIONS"
    assert next_prompt._extract_verdict(bold_label_body) == "APPROVE_WITH_CONDITIONS"


def test_release_flow_requires_gate_accept_then_merge(monkeypatch):
    base_pr = {
        "number": 77,
        "title": "feat: release flow",
        "body": """
## Required reviews
- Rhea (Release) - final gate
""",
        "reviewDecision": "",
        "labels": [{"name": "ready-for-review"}],
        "author": {"login": "ci4me"},
        "headRefName": "feat/release-flow",
        "baseRefName": "main",
        "comments": [
            {
                "body": "---\nPersona: Rhea\nRole: AI Release Manager\nLayer: assurance\nModel: test\nSource: PR #77\nSelf-review conflict: No\nRun-ID: x\n---\n\nREVIEW-VERDICT: APPROVE\n\n**Verdict:** APPROVE",
                "author": {"login": "ci4me"},
                "createdAt": "2026-05-23T00:00:00Z",
            }
        ],
        "reviews": [],
        # An actionable PR (touches source), so the validity filter keeps it in
        # scope; the release gate is what we're exercising here, not note-only
        # skipping.
        "files": [{"path": "app/release_flow.py"}, {"path": "README.md"}],
        "url": "https://github.com/ci4me/ai-erp-foundation/pull/77",
    }
    # resolve_priority lives in next_prompt_legacy and resolves _load_pr_details
    # in that module's namespace, so patch it there.
    monkeypatch.setattr(next_prompt_legacy, "_load_pr_details", lambda repo, number: base_pr)

    state = next_prompt.RepoState(
        open_prs=[base_pr],
        open_issues=[],
        open_discussions=[],
        existing_personas=set(next_prompt._persona_catalog()),
        existing_scenarios=set(next_prompt._scenario_catalog()),
        prs_with_changes_requested=[],
    )

    priority, context = next_prompt.resolve_priority(state, "ci4me/ai-erp-foundation")
    assert priority == "merge_gate"

    base_pr["comments"].append({"body": "RHEA-VERDICT: MERGE_READY\n\n**Gate checklist:** PASS", "author": {"login": "ci4me"}})
    priority, context = next_prompt.resolve_priority(state, "ci4me/ai-erp-foundation")
    assert priority == "accept_pr"

    base_pr["comments"].append({"body": "ACCEPTANCE-DECISION: ACCEPT\n\n**Evidence:** gates passed", "author": {"login": "ci4me"}})
    priority, context = next_prompt.resolve_priority(state, "ci4me/ai-erp-foundation")
    assert priority == "merge_pr"


def test_explicit_team_request_becomes_create_issue():
    state = next_prompt.RepoState(
        open_prs=[],
        open_issues=[
            {
                "number": 42,
                "title": "Inbox request",
                "body": "TEAM-REQUEST: Build a new feature to export paid invoices as CSV.",
                "labels": [{"name": "request:team"}],
            }
        ],
        open_discussions=[],
        existing_personas=set(next_prompt._persona_catalog()),
        existing_scenarios=set(next_prompt._scenario_catalog()),
        prs_with_changes_requested=[],
    )

    priority, context = next_prompt.resolve_priority(state, "ci4me/ai-erp-foundation")

    assert priority == "create_issue"
    assert context["source_kind"] == "issue"
    variables = next_prompt._issue_lifecycle_variables(context, "create_issue")
    assert "export paid invoices" in variables["proposed_issue_title"]
