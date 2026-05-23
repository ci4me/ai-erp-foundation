---
id: discussion
description: Respond to a discussion thread with a structured, signed reply
---

# Discussion Response

## Chain of Thought (complexity-based)

Length is set by :func:`simulation.tools.complexity.get_cot_requirements`:

- Trivial (label ``trivial`` or ``quick-fix``): 1 step × 3 words; CoT optional.
- Medium (default): 3 steps × 8 words.
- Complex (label ``complex``, ``risk:high``, ``risk:critical`` or keywords like
  *architecture*, *database*, *security*): 5 steps × 12 words.

```
**Reasoning:**
1. [step 1]
2. [step 2]
...
```

## Response

Write a concise, helpful answer that:

1. Acknowledges the asker's specific concern by name or short quote.
2. Names the next concrete step or decision needed (or marks the thread
   resolved).
3. References any decision-log entry (`<!-- DECISIONS: ... -->`) the
   reply must respect.

End with one of:

```
DISCUSSION-STATUS: RESOLVED
DISCUSSION-STATUS: NEEDS_FOLLOWUP
```

This template is intentionally orphan from `catalog.yml`. The active
discussion action is still `comment_discussion`; `discussion.md` is the
short-form template the chained/inline variant can render when a
follow-up reply is generated via `CHAIN-NEXT: comment_discussion`.
