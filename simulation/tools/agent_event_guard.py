"""GitHub Actions guard for autonomous-loop comments/reviews.

Reads a GitHub webhook event payload, extracts the comment/review body, infers
the autonomous-loop action, and runs agent_output_validator. Human comments that
are not signed agent outputs and do not contain state markers are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from simulation.tools import agent_output_validator, next_prompt


def _event_body(event: dict[str, Any]) -> tuple[str, bool]:
    if isinstance(event.get("comment"), dict):
        body = str(event["comment"].get("body") or "")
        issue = event.get("issue") or {}
        return body, bool(isinstance(issue, dict) and issue.get("pull_request"))
    if isinstance(event.get("review"), dict):
        return str(event["review"].get("body") or ""), True
    if isinstance(event.get("discussion"), dict):
        return str(event["discussion"].get("body") or ""), False
    return "", False


def _expected_persona(body: str) -> str | None:
    header, _ = agent_output_validator.parse_persona_header(body)
    if not header:
        return None
    aliases = next_prompt._persona_aliases(next_prompt._load_persona_index())
    token = next_prompt._normalize_persona_token(str(header.get("Persona") or ""))
    return aliases.get(token) or aliases.get(token.split("-", 1)[0])


def validate_event(event: dict[str, Any], *, event_name: str | None = None) -> agent_output_validator.ValidationResult | None:
    body, is_pr = _event_body(event)
    if not agent_output_validator.body_looks_like_agent_output(body):
        return None
    action = agent_output_validator.infer_action(body, github_event_name=event_name, is_pr=is_pr)
    persona = _expected_persona(body)
    return agent_output_validator.validate_agent_output(body, persona_id=persona, action=action)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the current GitHub event if it is an agent output.")
    parser.add_argument("--event-file", type=Path, required=True)
    parser.add_argument("--event-name", default=None)
    args = parser.parse_args()

    event = json.loads(args.event_file.read_text())
    result = validate_event(event, event_name=args.event_name)
    if result is None:
        print("SKIP non-agent comment/review")
        return 0
    if result.valid:
        print(f"VALID action={result.action or 'unknown'} verdict={result.verdict or 'none'}")
        return 0
    print(f"INVALID action={result.action or 'unknown'}", file=sys.stderr)
    for error in result.errors:
        print(f"- {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
