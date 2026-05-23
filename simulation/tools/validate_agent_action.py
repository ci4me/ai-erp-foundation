"""Validate autonomous-agent GitHub comments, reviews, and lifecycle markers.

The autonomous loop asks agents to mutate GitHub state by posting PR reviews,
issue comments, discussion comments, acceptance decisions, close decisions, and
end-of-run summaries. This validator is the mechanical backstop: it checks that
an agent action has the required signed header, lifecycle marker, template
sections, allowed verdicts, and no unresolved placeholders.

Usage examples:

    python -m simulation.tools.validate_agent_action --kind pr-review \
        --persona mara-product-owner --file /tmp/pr-35-mara-review.md

    python -m simulation.tools.validate_agent_action --kind discussion-comment \
        --persona iris-security --file /tmp/discussion-12-iris-comment.md

    python -m simulation.tools.validate_agent_action --kind auto --file body.md --json

Exit codes:

- 0: valid.
- 1: validation failed.
- 2: invalid CLI usage or unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Reuse repo-owned persona loading when available.
    from simulation.tools import next_prompt
except Exception:  # pragma: no cover - defensive for direct file execution.
    next_prompt = None  # type: ignore[assignment]


HEADER_KEYS = (
    "Persona",
    "Role",
    "Layer",
    "Model",
    "Source",
    "Self-review conflict",
    "Run-ID",
)

PLACEHOLDER_PATTERNS = (
    r"\bCHANGE_ME\b",
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bPASTE\b",
    r"COPY YOUR",
    r"\bFIXME\b",
    r"\bLorem ipsum\b",
    r"\[ISSUE_NUMBER\]",
    r"\[PR_NUMBER\]",
    r"\[DISCUSSION_NUMBER\]",
    r"\[MILESTONE_TITLE\]",
    r"\[A-Z0-9_ -]+\]",
)

PR_REVIEW_REQUIRED_SECTIONS = (
    "**Verdict:**",
    "**Acceptance matrix:**",
    "**Blocking findings:**",
    "**Non-blocking findings:**",
    "**Required next action:**",
)

DISCUSSION_REQUIRED_SECTIONS = (
    "**Discussion state:**",
    "**Response:**",
    "**Evidence from discussion:**",
    "**Required next action:**",
    "DISCUSSION-STATE:",
)

ACCEPTANCE_REQUIRED_SECTIONS = (
    "ACCEPTANCE-DECISION:",
    "**Decision:**",
    "**Gate evidence:**",
    "**Reason:**",
    "**Next action:**",
)

ISSUE_CLOSE_REQUIRED_SECTIONS = (
    "ISSUE-STATE:",
    "**Reason:**",
    "**Evidence:**",
)

VALID_DISCUSSION_STATES = {"OPEN", "RESOLVED", "PROMOTED", "DEFERRED", "CLOSED", "NO_ACTION"}
VALID_ACCEPTANCE_DECISIONS = {"ACCEPT", "HOLD", "REJECT"}


@dataclass
class ValidationResult:
    kind: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_persona: str | None = None
    detected_verdict: str | None = None
    detected_marker: str | None = None

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "detected_persona": self.detected_persona,
            "detected_verdict": self.detected_verdict,
            "detected_marker": self.detected_marker,
        }


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _split_header(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        return {}, text
    header: dict[str, str] = {}
    for raw_line in parts[1].splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        header[key.strip()] = value.strip().strip('"')
    return header, parts[2].strip()


def _normalize_token(value: str) -> str:
    value = re.sub(r"`|\*|_", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.split(r"\s+[–—-]\s+|\s+/\s+|:", value, maxsplit=1)[0]
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return value.strip("-")


def _persona_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    if next_prompt is None:
        return aliases
    try:
        personas = next_prompt._load_persona_index()  # type: ignore[attr-defined]
        catalog = next_prompt._persona_catalog()  # type: ignore[attr-defined]
    except Exception:
        return aliases
    for persona_id in catalog:
        aliases[persona_id] = persona_id
        aliases[persona_id.split("-", 1)[0]] = persona_id
    for persona_id, doc in personas.items():
        aliases[persona_id] = persona_id
        aliases[persona_id.split("-", 1)[0]] = persona_id
        name = str(doc.frontmatter.get("name") or "")
        if name:
            normalized = _normalize_token(name)
            aliases[normalized] = persona_id
            aliases[normalized.split("-", 1)[0]] = persona_id
    return aliases


def _allowed_verdicts(persona_id: str | None) -> set[str]:
    if not persona_id or next_prompt is None:
        return set()
    try:
        personas = next_prompt._load_persona_index()  # type: ignore[attr-defined]
        doc = personas.get(persona_id)
        if not doc:
            return set()
        raw = doc.frontmatter.get("verdict_enum") or []
        if isinstance(raw, str):
            return {raw}
        return {str(item) for item in raw}
    except Exception:
        return set()


def _extract_verdict(text: str) -> str | None:
    patterns = (
        r"\*\*(?:Final\s+)?[Vv]erdict:\s*`?([^*`\n]+)`?\*\*",
        r"\*\*(?:Final\s+)?[Vv]erdict:\*\*\s*`?([^`\n]+)`?",
        r"^##\s+(?:Final\s+)?[Vv]erdict:\s*`?([^`\n]+)`?",
        r"^\s*(?:Final\s+)?[Vv]erdict:\s*`?([^`\n]+)`?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1).strip().strip("*`").replace(" ", "_")
    return None


def _contains_placeholder(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in PLACEHOLDER_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            hits.append(match.group(0))
    return hits


def _validate_header(text: str, result: ValidationResult, expected_persona: str | None) -> tuple[dict[str, str], str]:
    header, body = _split_header(text)
    if not header:
        result.fail("Missing signed YAML-style persona header delimited by --- lines.")
        return header, body

    for key in HEADER_KEYS:
        if not header.get(key):
            result.fail(f"Missing header key: {key}")

    persona_raw = header.get("Persona", "")
    aliases = _persona_aliases()
    detected = aliases.get(_normalize_token(persona_raw)) or persona_raw
    result.detected_persona = detected

    if expected_persona:
        expected = aliases.get(_normalize_token(expected_persona)) or expected_persona
        if detected != expected:
            result.fail(f"Persona mismatch: expected {expected!r}, got {detected!r}.")

    if "CHANGE_ME" in header.get("Run-ID", "") or not header.get("Run-ID"):
        result.fail("Run-ID is missing or unresolved.")
    if header.get("Self-review conflict") not in {"Yes", "No"}:
        result.fail("Self-review conflict must be exactly Yes or No.")
    return header, body


def _validate_no_placeholders(text: str, result: ValidationResult) -> None:
    for hit in _contains_placeholder(text):
        result.fail(f"Unresolved placeholder/token found: {hit}")


def _require_tokens(text: str, tokens: tuple[str, ...], result: ValidationResult) -> None:
    for token in tokens:
        if token not in text:
            result.fail(f"Missing required section or marker: {token}")


def _validate_pr_review(text: str, result: ValidationResult, expected_persona: str | None) -> None:
    _header, body = _validate_header(text, result, expected_persona)
    _validate_no_placeholders(text, result)
    _require_tokens(text, PR_REVIEW_REQUIRED_SECTIONS, result)

    verdict = _extract_verdict(text)
    result.detected_verdict = verdict
    if not verdict:
        result.fail("Missing parseable Verdict line.")
    else:
        persona_for_verdict = expected_persona or result.detected_persona
        allowed = _allowed_verdicts(persona_for_verdict)
        if allowed and verdict not in allowed:
            result.fail(f"Verdict {verdict!r} is not allowed for {persona_for_verdict}; allowed: {sorted(allowed)}")

    if "| Criterion | Status | Evidence" not in text:
        result.fail("Acceptance matrix must include the standard Criterion/Status/Evidence table header.")
    if re.search(r"\|\s*CHANGE_ME", text):
        result.fail("Acceptance matrix still contains placeholder row content.")
    if verdict == "APPROVE" and re.search(r"\bMISSING\b|NOT_FOUND_IN_DIFF", body, re.IGNORECASE):
        result.fail("APPROVE cannot coexist with MISSING or NOT_FOUND_IN_DIFF evidence.")


def _validate_discussion_comment(text: str, result: ValidationResult, expected_persona: str | None) -> None:
    _validate_header(text, result, expected_persona)
    _validate_no_placeholders(text, result)
    _require_tokens(text, DISCUSSION_REQUIRED_SECTIONS, result)
    marker = _extract_marker_line(text, "DISCUSSION-STATE:")
    result.detected_marker = marker
    if marker:
        state = marker.split(":", 1)[1].strip().split()[0].upper()
        if state not in VALID_DISCUSSION_STATES:
            result.fail(f"Invalid discussion state {state!r}; expected one of {sorted(VALID_DISCUSSION_STATES)}.")


def _validate_acceptance_decision(text: str, result: ValidationResult, expected_persona: str | None) -> None:
    _validate_header(text, result, expected_persona)
    _validate_no_placeholders(text, result)
    _require_tokens(text, ACCEPTANCE_REQUIRED_SECTIONS, result)
    match = re.search(r"^ACCEPTANCE-DECISION:\s*(ACCEPT|HOLD|REJECT)\s+PR#\d+\s+--\s+(.+)$", text, re.MULTILINE)
    if not match:
        result.fail("ACCEPTANCE-DECISION must be exactly: ACCEPTANCE-DECISION: ACCEPT|HOLD|REJECT PR#N -- reason")
    else:
        decision = match.group(1)
        result.detected_marker = f"ACCEPTANCE-DECISION: {decision}"
        if decision not in VALID_ACCEPTANCE_DECISIONS:
            result.fail(f"Invalid acceptance decision: {decision}")
        if len(match.group(2).strip()) < 8:
            result.fail("Acceptance decision reason is too short.")


def _validate_issue_close(text: str, result: ValidationResult, expected_persona: str | None) -> None:
    _validate_header(text, result, expected_persona)
    _validate_no_placeholders(text, result)
    _require_tokens(text, ISSUE_CLOSE_REQUIRED_SECTIONS, result)
    marker = _extract_marker_line(text, "ISSUE-STATE:")
    result.detected_marker = marker
    if marker and not re.search(r"ISSUE-STATE:\s*(READY_TO_CLOSE|CLOSED|REJECTED|ACCEPTED)", marker):
        result.fail("ISSUE-STATE must be READY_TO_CLOSE, CLOSED, ACCEPTED, or REJECTED.")


def _validate_summary(text: str, result: ValidationResult, expected_persona: str | None) -> None:
    _validate_header(text, result, expected_persona)
    _validate_no_placeholders(text, result)
    _require_tokens(text, ("## End-of-run summary",), result)


def _validate_generic(text: str, result: ValidationResult, expected_persona: str | None) -> None:
    _validate_header(text, result, expected_persona)
    _validate_no_placeholders(text, result)


def _extract_marker_line(text: str, marker: str) -> str | None:
    pattern = re.compile(rf"({re.escape(marker)}\s*[^\n]+)")
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def detect_kind(text: str) -> str:
    if "ACCEPTANCE-DECISION:" in text:
        return "acceptance-decision"
    if "DISCUSSION-STATE:" in text or "**Discussion state:**" in text:
        return "discussion-comment"
    if "ISSUE-STATE:" in text:
        return "issue-close"
    if "## End-of-run summary" in text:
        return "summary"
    if "**Verdict:**" in text and "**Acceptance matrix:**" in text:
        return "pr-review"
    return "generic"


def validate(text: str, *, kind: str = "auto", persona: str | None = None) -> ValidationResult:
    actual_kind = detect_kind(text) if kind == "auto" else kind
    result = ValidationResult(kind=actual_kind)
    validators = {
        "pr-review": _validate_pr_review,
        "discussion-comment": _validate_discussion_comment,
        "acceptance-decision": _validate_acceptance_decision,
        "issue-close": _validate_issue_close,
        "summary": _validate_summary,
        "generic": _validate_generic,
    }
    validator = validators.get(actual_kind)
    if validator is None:
        result.fail(f"Unsupported validation kind: {actual_kind}")
        return result
    validator(text, result, persona)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate autonomous-loop agent action bodies.")
    parser.add_argument("--kind", default="auto", choices=["auto", "pr-review", "discussion-comment", "acceptance-decision", "issue-close", "summary", "generic"])
    parser.add_argument("--persona", default=None, help="Expected persona id/name, e.g. mara-product-owner.")
    parser.add_argument("--file", required=True, help="Markdown body file to validate, or '-' for stdin.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable result JSON.")
    args = parser.parse_args(argv)

    try:
        text = _read_text(args.file)
    except OSError as exc:
        print(f"ERROR: could not read input: {exc}", file=sys.stderr)
        return 2

    result = validate(text, kind=args.kind, persona=args.persona)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif result.ok:
        print(f"ok: {result.kind}")
        if result.detected_persona:
            print(f"persona: {result.detected_persona}")
        if result.detected_verdict:
            print(f"verdict: {result.detected_verdict}")
        if result.detected_marker:
            print(f"marker: {result.detected_marker}")
    else:
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
