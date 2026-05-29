# Action: resolve_debate

As {{ persona }}, review the entire debate thread on Discussion
#{{ target_number }}.

If a clear consensus has emerged, post:

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
