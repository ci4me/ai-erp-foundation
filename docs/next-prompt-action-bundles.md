# `next_prompt.py` same-persona action bundles

## Goal

Allow one generated autonomous-loop prompt to execute more than one legal action
for the same persona when the actions are independent, not blocked, and not
terminal lifecycle steps.

The design keeps the current identity rule:

```text
one prompt = one selected persona
```

The selected persona may receive a primary action plus a small number of
compatible additional actions.

## Selection contract

A bundle has:

- `selected_persona`
- `primary_action`
- `additional_actions`

Additional actions are eligible only when all of the following are true:

1. They use the same persona as the primary action.
2. Neither action is terminal or lifecycle-locking.
3. Both actions are marked as independent.
4. The actions target different GitHub objects.
5. The action does not require a result produced earlier in the same prompt.

## Examples

Compatible:

```text
review_pr #35 + comment_discussion #21
triage_issue #3 + open_followup_issue #7
```

Not compatible:

```text
merge_gate #35 + merge_pr #35
address_changes_requested #35 + review_pr #35
triage_issue #3 + open_followup_issue #3
```

## Rendering contract

If the bundle contains more than one action, the rendered prompt should front-load
an `ACTION BUNDLE` section before the informational persona action menu. For each
action, include:

- action id;
- target object reference;
- exact intent;
- whether content is inline or fetch-required;
- step-by-step execution instructions;
- validation command;
- posting command.

The persona action menu remains useful, but it must be clearly labeled as
informational, such as `Other legal actions for this persona`.

## Size-aware content rule

Small payloads should be inline and self-contained. Large payloads should include
a concise summary plus exact fetch instructions. The default helper threshold is
20,000 characters.

Review and merge actions can continue using the existing diff truncation logic.
Small issue/discussion/comment actions should usually inline their bodies.

## Implementation status

This PR introduces `simulation.tools.action_bundles` with conservative bundle
helpers and tests. The next integration step is to wire `next_prompt.py` so
`resolve_priority()` can delegate to a `resolve_action_bundle()` flow while
keeping the existing single-action fallback.
