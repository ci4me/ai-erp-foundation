# Code Maintenance Notes

## What to keep

Keep files that are part of one of these surfaces:

- action templates and marker registry;
- persona prompts and roster;
- `next_prompt.py` and validator tools;
- tests under `simulation/tests`;
- docs that explain operation, validation, and lifecycle.

## What to remove

Remove duplicate templates that are not referenced by the action catalog. The
static coverage check expects every template to have one catalog owner.

## Documentation style

- Public tools should have module docstrings explaining intent and safety model.
- Helper functions should explain why they exist when the reason is not obvious.
- Comments should document state-machine decisions, not repeat the code.
- Templates should teach a cold agent what to read, what to write, how to verify,
  and when to stop.
