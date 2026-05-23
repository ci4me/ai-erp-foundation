---
id: security-audit
description: Security audit outside normal PR review
---

## Action: Security Audit

Persona: {{persona_name}} (`{{persona_id}}`)

## Steps

1. Enumerate assets, secrets, permissions, trust boundaries, and actors.
2. Check workflow permissions, fork behavior, `workflow_dispatch` inputs, token scopes, and prompt-injection surfaces.
3. Post threat model with blocking mitigations and evidence.

Use `post_mode={{post_mode}}` for all mutation steps.
