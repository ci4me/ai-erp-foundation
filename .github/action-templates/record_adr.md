# Action: record_adr

You are {{ persona }}. A significant architectural decision has been made.

Create a new file under `docs/adr/` from the template below, commit it on a new
branch, and open a PR labeled `adr`. Announce it with the marker:

```
EXPLANATION: ADR-{{ number }} {{ title }}
```

Template:

```markdown
# ADR-{{ number }}: {{ title }}

Date: {{ date }}
Status: proposed | accepted | deprecated | superseded
Deciders: {{ persona }}, ...

## Context and Problem Statement
...

## Decision
...

## Consequences
...
```
