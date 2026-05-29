---
id: re-ratification
description: 30-day operating-model re-ratification
---

## Action: Re-ratification

Persona: {{persona_name}} (`{{persona_id}}`)

Compare `docs/product-vision.md` metrics, friction cost, defect escape rate, and governance benefit. Verdict must be one of: RE_RATIFY, AMEND, ROLLBACK.


## Required output marker

End your posted comment/review with the machine-readable state marker so the
autonomous loop can parse the outcome:

```
RERATIFICATION: RATIFY
```

Allowed values: `RATIFY`, `AMEND`, `ROLLBACK`.
