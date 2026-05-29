"""Validate autonomous-loop agent outputs.

The autonomous loop must never trust free-form prose as state. This validator
checks that a proposed or posted GitHub comment/review/discussion response is
machine-parseable, signed by a persona, and shaped for the action it claims to
complete.

It is intentionally offline: pass it a body file and, optionally, an action id
and expected persona id. GitHub Actions can run it on issue_comment,
pull_request_review, pull_request_review_comment, and discussion_comment events.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from simulation.tools import marker_registry, next_prompt


REQUIRED_HEADER_FIELDS = [
    "Persona",
    "Role",
    "Layer",
    "Model",
    "Source",
    "Self-review conflict",
    "Run-ID",
]

MACHINE_STATE_MARKERS = marker_registry.marker_names()

# Actions that still require the human-readable `**Verdict:**` line in
# addition to their machine marker. Most lifecycle actions are marker-only
# because the marker itself is the verdict/state transition.
VERDICT_REQUIRED_ACTIONS = {"review_pr", "comment_discussion", "triage_issue"}


ACTION_VERDICT_ENUMS: dict[str, set[str]] = {
    "comment_discussion": {"PROPOSE", "DEFER", "WITHDRAW", "PROMOTE", "COMMENT"},
}


ACTION_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "review_pr": [
        ("verdict line", r"(?im)^\s*\*\*Verdict:\*\*\s*[^\n]+"),
        ("acceptance matrix heading", r"(?im)^\s*\*\*Acceptance matrix:\*\*"),
        ("acceptance matrix table header", r"(?im)^\s*\|\s*Criterion\s*\|\s*Status\s*\|\s*Evidence"),
        ("blocking findings section", r"(?im)^\s*\*\*Blocking findings"),
        ("non-blocking findings section", r"(?im)^\s*\*\*Non-blocking findings"),
        ("required next action section", r"(?im)^\s*\*\*Required next action:\*\*"),
    ],
    "comment_discussion": [
        ("discussion response heading", r"(?im)^\s*##\s+Discussion response"),
        ("verdict line", r"(?im)^\s*\*\*Verdict:\*\*\s*[^\n]+"),
        ("reasoning line", r"(?im)^\s*\*\*Reasoning:\*\*\s*[^\n]+"),
        ("required next action line", r"(?im)^\s*\*\*Required next action:\*\*\s*[^\n]+"),
    ],
    "request_review": [
        ("review request marker", r"(?im)^\s*REVIEW-REQUEST:\s*(human|[a-z0-9][a-z0-9-]+)\b"),
        ("reason", r"(?im)^\s*\*\*Reason:\*\*\s*[^\n]+"),
    ],
    "close_discussion": [
        ("discussion terminal marker", r"(?im)^\s*DISCUSSION-STATE:\s*(PROMOTED|REJECTED|CLOSED|RESOLVED|ANSWERED|SUPERSEDED)\b"),
        ("reason", r"(?im)^\s*\*\*Reason:\*\*\s*[^\n]+"),
    ],
    "resolve_review_thread": [
        ("review thread marker", r"(?im)^\s*REVIEW-THREAD-STATE:\s*RESOLVED\b"),
        ("evidence", r"(?im)^\s*\*\*Evidence:\*\*\s*[^\n]+"),
    ],
    "accept_pr": [
        ("acceptance decision marker", r"(?im)^\s*ACCEPTANCE-DECISION:\s*ACCEPT\b"),
        ("evidence", r"(?im)^\s*\*\*Evidence:\*\*\s*[^\n]+"),
    ],
    "reject_pr": [
        ("reject marker", r"(?im)^\s*(ACCEPTANCE-DECISION:\s*REJECT|PR-STATE:\s*REJECTED)\b"),
        ("reason", r"(?im)^\s*\*\*Reason:\*\*\s*[^\n]+"),
    ],
    "create_issue": [
        ("issue created marker", r"(?im)^\s*ISSUE-STATE:\s*CREATED\b"),
        ("source section", r"(?im)^\s*##\s+Source\b"),
        ("acceptance criteria", r"(?im)^\s*##\s+Acceptance criteria\b"),
    ],
    "open_issue": [
        ("issue opened marker", r"(?im)^\s*ISSUE-OPENED:\s*OPENED\b"),
        ("source section", r"(?im)^\s*##\s+Source\b"),
        ("acceptance criteria", r"(?im)^\s*##\s+Acceptance criteria\b"),
    ],
    "close_issue": [
        ("issue terminal marker", r"(?im)^\s*ISSUE-STATE:\s*CLOSED\b"),
        ("close reason", r"(?im)^\s*\*\*Close reason:\*\*\s*(completed|not_planned|duplicate)\b"),
    ],
    "reopen_issue": [
        ("issue reopen marker", r"(?im)^\s*ISSUE-REOPENED:\s*REOPENED\b"),
        ("reason", r"(?im)^\s*\*\*Reason:\*\*\s*[^\n]+"),
    ],
    "merge_gate": [
        ("rhea verdict marker", r"(?im)^\s*RHEA-VERDICT:\s*(MERGE_READY|HOLD|BLOCKED|ACCEPT|REJECT)\b"),
        ("gate checklist", r"(?im)^\s*\*\*Gate checklist:\*\*"),
    ],
    "verify_agent_action": [
        ("validation result marker", r"(?im)^\s*VALIDATION-RESULT:\s*(PASS|FAIL)\b"),
    ],
}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str]
    header: dict[str, Any]
    verdict: str | None
    action: str | None = None


# Collaboration markers that must carry non-empty content when present.
_NONEMPTY_COLLAB_MARKERS = (
    "REQUEST-INFO",
    "RESPONSE",
    "ARGUMENT",
    "REBUTTAL",
    "EVIDENCE",
    "OBJECTION",
    "ESCALATION",
    "EXPLANATION",
    "DECISION-FROM-LEAD",
)


def _marker_content(body: str, marker: str) -> str | None:
    """Return the text after ``marker:`` on its line, or None if absent."""
    match = re.search(rf"(?im)^\s*{re.escape(marker)}:\s*(.*)$", body)
    return match.group(1).strip() if match else None


def validate_collaboration_markers(body: str) -> list[str]:
    """Validate collaboration markers when present (no-op if none appear).

    Rules:
    - REQUEST-INFO/RESPONSE/ARGUMENT/REBUTTAL/EVIDENCE/OBJECTION/ESCALATION/
      EXPLANATION/DECISION-FROM-LEAD must be non-empty.
    - RESOLUTION must state a decision and ``(approved/vetoed by <persona>)``.
    - COUNTER-PROPOSAL must reference another marker/comment (link, #ref, or
      replaces/amends ...).
    """
    errors: list[str] = []
    for marker in _NONEMPTY_COLLAB_MARKERS:
        if re.search(rf"(?im)^\s*{re.escape(marker)}:", body):
            if not _marker_content(body, marker):
                errors.append(f"{marker} marker must not be empty")

    if re.search(r"(?im)^\s*RESOLUTION:", body):
        content = _marker_content(body, "RESOLUTION") or ""
        if not re.search(r"\b(approved|vetoed)\s+by\s+\S+", content, re.IGNORECASE):
            errors.append("RESOLUTION must state a decision and '(approved/vetoed by <persona>)'")

    if re.search(r"(?im)^\s*COUNTER-PROPOSAL:", body):
        content = _marker_content(body, "COUNTER-PROPOSAL") or ""
        references = (
            re.search(r"https?://", content)
            or re.search(r"#\d+", content)
            or re.search(r"\b(replaces|amends)\b", content, re.IGNORECASE)
            or re.search(r"[A-Z][A-Z-]+:", content)
        )
        if not references:
            errors.append(
                "COUNTER-PROPOSAL must reference another marker/comment "
                "(a link, #ref, or 'replaces/amends ...')"
            )

    if re.search(r"(?im)^\s*CONSENSUS-REACHED:", body):
        content = _marker_content(body, "CONSENSUS-REACHED") or ""
        if not content:
            errors.append("CONSENSUS-REACHED marker must not be empty")
        else:
            handles = {h.lower() for h in re.findall(r"@([a-z0-9][a-z0-9-]+)", content, re.IGNORECASE)}
            if len(handles) < 2:
                errors.append(
                    "CONSENSUS-REACHED must list at least two distinct @persona handles "
                    "(e.g. 'signees: @a, @b')"
                )
    return errors


def parse_persona_header(body: str) -> tuple[dict[str, Any], str]:
    """Parse a leading YAML persona header from an agent output."""
    if not body.startswith("---\n"):
        return {}, body
    parts = body.split("---\n", 2)
    if len(parts) != 3:
        return {}, body
    raw_header = parts[1]
    remainder = parts[2]
    if yaml is not None:
        loaded = yaml.safe_load(raw_header) or {}
        if isinstance(loaded, dict):
            return loaded, remainder
    header: dict[str, Any] = {}
    for line in raw_header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        header[key.strip()] = value.strip()
    return header, remainder


def extract_verdict(body: str) -> str | None:
    """Extract the first machine-parseable verdict token from markdown."""
    patterns = [
        r"\*\*(?:Final\s+)?[Vv]erdict:?\*\*\s*`?([^`\n]+)`?",
        r"\*\*(?:Final\s+)?[Vv]erdict:?\s*`?([^*`\n]+)`?\*\*",
        r"^##\s+(?:Final\s+)?[Vv]erdict:?\s*`?([^`\n]+)`?",
        r"^\s*\*?\*?(?:Final\s+)?[Vv]erdict:?\*?\*?\s*`?([^`\n]+)`?",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.MULTILINE)
        if match:
            raw = match.group(1).strip().strip("*`:")
            return raw.split("|")[0].strip().replace(" ", "_")
    return None


def body_looks_like_agent_output(body: str) -> bool:
    """Return True when this body should be subject to validation."""
    if body.startswith("---\n") and "Persona:" in body.split("---\n", 2)[1]:
        return True
    return any(marker in body for marker in MACHINE_STATE_MARKERS)


def infer_action(body: str, *, github_event_name: str | None = None, is_pr: bool = False) -> str | None:
    """Infer the validation action from body markers and the GitHub event.

    The same marker prefix can appear in more than one lifecycle action. The
    clearest example is ``DISCUSSION-STATE:``: non-terminal values are normal
    discussion comments, while terminal values mean the close-discussion action
    completed. Keep the inference conservative so CI validates the action the
    agent actually performed instead of treating every discussion marker as a
    closure.
    """
    if re.search(r"(?im)^\s*ACCEPTANCE-DECISION:\s*ACCEPT\b", body):
        return "accept_pr"
    if re.search(r"(?im)^\s*(ACCEPTANCE-DECISION:\s*REJECT|PR-STATE:\s*REJECTED)\b", body):
        return "reject_pr"
    if re.search(r"(?im)^\s*ISSUE-STATE:\s*CREATED\b", body):
        return "create_issue"
    if re.search(r"(?im)^\s*ISSUE-OPENED:\s*OPENED\b", body):
        return "open_issue"
    if re.search(r"(?im)^\s*ISSUE-STATE:\s*CLOSED\b", body):
        return "close_issue"
    if re.search(r"(?im)^\s*ISSUE-REOPENED:\s*REOPENED\b", body):
        return "reopen_issue"
    if re.search(r"(?im)^\s*DISCUSSION-STATE:\s*(PROMOTED|REJECTED|CLOSED|RESOLVED|ANSWERED|SUPERSEDED)\b", body):
        return "close_discussion"
    if re.search(r"(?im)^\s*DISCUSSION-STATE:\s*(OPEN|NEEDS_COMMENT|NEEDS_PERSONA|DEFERRED|NO_ACTION)\b", body):
        return "comment_discussion"
    if re.search(r"(?im)^\s*REVIEW-REQUEST:\s*", body):
        return "request_review"
    if re.search(r"(?im)^\s*REVIEW-THREAD-STATE:\s*RESOLVED\b", body):
        return "resolve_review_thread"
    if re.search(r"(?im)^\s*RHEA-VERDICT:\s*", body):
        return "merge_gate"
    if re.search(r"(?im)^\s*VALIDATION-RESULT:\s*", body):
        return "verify_agent_action"
    if github_event_name == "discussion_comment":
        return "comment_discussion"
    if github_event_name == "pull_request_review":
        return "review_pr"
    if github_event_name == "issue_comment" and is_pr:
        return "review_pr"
    registry_matches = marker_registry.infer_actions_from_body(body)
    if registry_matches:
        return registry_matches[0]
    return None


def _persona_id_from_header(header: dict[str, Any]) -> str | None:
    if not header:
        return None
    aliases = next_prompt._persona_aliases(next_prompt._load_persona_index())
    token = next_prompt._normalize_persona_token(str(header.get("Persona") or ""))
    return aliases.get(token) or aliases.get(token.split("-", 1)[0])


def validate_agent_output(
    body: str,
    *,
    persona_id: str | None = None,
    action: str | None = None,
) -> ValidationResult:
    """Validate an agent comment/review body for loop-readability."""
    errors: list[str] = []
    header, remainder = parse_persona_header(body)

    if not header:
        errors.append("missing leading YAML persona header")
    for field in REQUIRED_HEADER_FIELDS:
        if field not in header or header[field] is None or str(header[field]).strip() == "":
            errors.append(f"missing header field: {field}")

    expected = persona_id or _persona_id_from_header(header)
    if persona_id:
        aliases = next_prompt._persona_aliases(next_prompt._load_persona_index())
        header_persona = str(header.get("Persona") or "")
        parsed = aliases.get(next_prompt._normalize_persona_token(header_persona))
        if parsed and parsed != persona_id:
            errors.append(f"header persona {parsed} does not match expected {persona_id}")

    verdict = extract_verdict(remainder)
    if not verdict and (action in VERDICT_REQUIRED_ACTIONS or action is None):
        errors.append("missing verdict")

    if verdict:
        action_allowed = ACTION_VERDICT_ENUMS.get(action or "")
        if action_allowed:
            if verdict not in action_allowed:
                errors.append(
                    f"verdict {verdict} is not allowed for action {action}; allowed: {', '.join(sorted(action_allowed))}"
                )
        elif expected:
            persona = next_prompt._load_persona_index().get(expected)
            if persona:
                allowed = set(next_prompt._as_list(persona.frontmatter.get("verdict_enum")))
                if allowed and verdict not in allowed:
                    errors.append(
                        f"verdict {verdict} is not allowed for {expected}; allowed: {', '.join(sorted(allowed))}"
                    )

    placeholder_patterns = [r"(?<!\$){{\s*[a-zA-Z0-9_]+\s*}}", r"\bCHANGE_ME\b", r"\[[A-Z][A-Z_ /|.-]*\]"]
    for pattern in placeholder_patterns:
        if re.search(pattern, body):
            errors.append(f"unresolved placeholder matched: {pattern}")

    if action:
        marker_spec = marker_registry.get_marker_spec(action)
        if marker_spec and not marker_spec.matches(remainder):
            errors.append(
                f"missing action marker: expected `{marker_spec.example()}` matching {marker_spec.regex}"
            )
        for description, pattern in ACTION_PATTERNS.get(action, []):
            if not re.search(pattern, remainder):
                errors.append(f"missing action field: {description}")

    if action == "review_pr" and "none" not in remainder.lower():
        # Review comments must cite evidence unless a section explicitly says none.
        evidence_like = re.search(r"[A-Za-z0-9_./-]+\.(php|py|md|yml|yaml|json|txt):\d+", remainder)
        diff_like = re.search(r"diff\s+hunk|@@\s+-\d+", remainder, re.IGNORECASE)
        if not evidence_like and not diff_like:
            errors.append("review_pr output lacks path:line or diff-hunk evidence")

    # Collaboration markers are additive and presence-gated: outputs that carry
    # none of them are unaffected.
    errors.extend(validate_collaboration_markers(body))

    return ValidationResult(valid=not errors, errors=errors, header=header, verdict=verdict, action=action)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an autonomous-loop agent output body.")
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--persona", default=None, help="Expected persona id, e.g. iris-security")
    parser.add_argument("--action", default=None, help="Expected action id, e.g. review_pr or comment_discussion")
    args = parser.parse_args()

    body = args.body_file.read_text()
    action = args.action or infer_action(body)
    result = validate_agent_output(body, persona_id=args.persona, action=action)
    if result.valid:
        print(f"VALID action={result.action or 'unknown'} verdict={result.verdict or 'none'}")
        return 0
    print(f"INVALID action={result.action or action or 'unknown'}", file=sys.stderr)
    for error in result.errors:
        print(f"- {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
