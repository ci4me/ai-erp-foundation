# Action: reach_consensus

As {{ persona }}, review the debate thread on Discussion #{{ target_number }} and
determine whether at least **two distinct personas** (including yourself, if
appropriate) have expressed clear agreement on a path forward.

If they have, post the consensus marker:

```
CONSENSUS-REACHED: <decision> (signees: @persona1, @persona2)
```

The `signees` list must name at least two distinct persona handles. Consensus is
the preferred, strongest resolution — the loop treats it as terminal.

If no consensus exists yet, do nothing and allow the debate to continue (or fall
back to a single-persona `RESOLUTION:` or an `ESCALATION:` to the Lead).

Sign your post with the persona header.
