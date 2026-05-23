from simulation.tools.action_bundles import (
    ActionSelection,
    actions_are_compatible,
    build_action_bundle,
    render_bundle_summary,
    should_inline_content,
)


def test_same_persona_independent_actions_are_compatible() -> None:
    primary = ActionSelection(
        action_id="review_pr",
        persona_id="iris-security",
        context={"pr": {"number": 35}},
    )
    candidate = ActionSelection(
        action_id="comment_discussion",
        persona_id="iris-security",
        context={"discussion": {"number": 21}},
    )

    assert actions_are_compatible(primary, candidate)


def test_different_personas_are_not_compatible() -> None:
    primary = ActionSelection(action_id="review_pr", persona_id="iris-security", context={"pr": {"number": 35}})
    candidate = ActionSelection(action_id="comment_discussion", persona_id="mara-product-owner", context={"discussion": {"number": 21}})

    assert not actions_are_compatible(primary, candidate)


def test_terminal_actions_are_not_bundled() -> None:
    primary = ActionSelection(action_id="merge_pr", persona_id="rhea-release-manager", context={"pr": {"number": 35}})
    candidate = ActionSelection(action_id="comment_discussion", persona_id="rhea-release-manager", context={"discussion": {"number": 21}})

    assert not actions_are_compatible(primary, candidate)


def test_same_object_actions_are_not_bundled() -> None:
    primary = ActionSelection(action_id="triage_issue", persona_id="mara-product-owner", context={"issue": {"number": 3}})
    candidate = ActionSelection(action_id="open_followup_issue", persona_id="mara-product-owner", context={"issue": {"number": 3}})

    assert not actions_are_compatible(primary, candidate)


def test_build_action_bundle_keeps_order_and_limits_extra_actions() -> None:
    primary = ActionSelection(action_id="triage_issue", persona_id="mara-product-owner", context={"issue": {"number": 3}})
    candidates = [
        ActionSelection(action_id="open_followup_issue", persona_id="mara-product-owner", context={"issue": {"number": 7}}),
        ActionSelection(action_id="comment_discussion", persona_id="mara-product-owner", context={"discussion": {"number": 21}}),
        ActionSelection(action_id="generate_ideas", persona_id="mara-product-owner", context={"discussion": {"number": 22}}),
    ]

    bundle = build_action_bundle(primary, candidates, max_additional_actions=2)

    assert [action.action_id for action in bundle.actions] == [
        "triage_issue",
        "open_followup_issue",
        "comment_discussion",
    ]


def test_should_inline_content_uses_character_limit() -> None:
    assert should_inline_content("small", inline_char_limit=10)
    assert not should_inline_content("too long", inline_char_limit=3)


def test_render_bundle_summary_marks_fetch_required_for_large_payload() -> None:
    bundle = build_action_bundle(
        ActionSelection(
            action_id="review_pr",
            persona_id="iris-security",
            context={"pr": {"number": 35}},
            payload="small",
            summary="Review PR #35",
        ),
        [
            ActionSelection(
                action_id="comment_discussion",
                persona_id="iris-security",
                context={"discussion": {"number": 21}},
                payload="x" * 20,
                summary="Comment on discussion #21",
            )
        ],
    )

    rendered = render_bundle_summary(bundle, inline_char_limit=10)

    assert "## ACTION BUNDLE" in rendered
    assert "Review PR #35 (inline)" in rendered
    assert "Comment on discussion #21 (fetch-required)" in rendered
    assert "Do not choose the next action yourself." in rendered
