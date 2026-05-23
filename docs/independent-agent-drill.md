# Independent Agent Drill

This drill proves the loop can move without hidden chat context.

## Procedure

1. Create a fixture GitHub state with one PR needing two reviews.
2. Run `next_prompt.py --probe-only` against a fake `gh` shim.
3. Confirm the selected action is `review_pr` and the selected persona is Iris.
4. Write a signed Iris review with `REVIEW-VERDICT:`.
5. Validate it with `agent_output_validator`.
6. Add that review to the fixture state.
7. Run `next_prompt.py --probe-only` again.
8. Confirm the selected persona advances to Mara.

The automated regression is:

```bash
python3 -m pytest simulation/tests/test_loop_progression.py -q
```

Expected result: the first run selects Iris; after the valid Iris marker is
present, the second run selects Mara. That demonstrates the loop advances by
reading GitHub-shaped state, not by remembering the previous chat.
