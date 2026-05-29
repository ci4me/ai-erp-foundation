# Action: resolve_debate

As {{ persona }}, review the entire debate thread on Discussion
#{{ target_number }}.

**Prefer consensus.** If at least two distinct personas have expressed clear
agreement, post the strongest resolution — a multi-persona consensus:

```
CONSENSUS-REACHED: <decision> (signees: @persona1, @persona2)
```

Otherwise, if a clear decision has emerged that you can own alone, post:

```
RESOLUTION: <decision> (approved by {{ persona }})
```

If you hold Lead authority and must decide unilaterally, post instead:

```
DECISION-FROM-LEAD: <binding decision>
```

If neither applies (no consensus and you are not the Lead), trigger an
escalation:

```
ESCALATION: <summary of the deadlock> (please decide)
```

Sign your post with the persona header.
