"""Strengthened marker parsing for the autonomous-loop scheduler.

This module is the single source of truth for *whether* a chunk of GitHub text
(comment, review body, discussion reply) contains a recognized state marker. It
intentionally lives next to ``marker_registry`` rather than replacing it:

- ``marker_registry`` owns the *catalog* of legal markers (loaded from
  ``markers.yml``).
- ``validator`` owns the *parser* — it knows how markers may appear in real
  user prose and what to do with malformed or unknown markers.

Hardening, in order of importance:

1. Case-insensitive matching and tolerant whitespace.
2. Markers inside fenced code blocks (``` ... ```) are ignored, and lines
   indented four or more spaces are treated as code blocks too.
3. Extra trailing text after the value is tolerated but logged as a warning.
4. Values outside the declared enum are rejected (strict).
5. Unknown markers are surfaced as ``UnknownMarker`` so the orchestrator can
   route to ``request_clarification`` instead of silently dropping the signal.
6. Approval markers in very short comments are flagged as suspicious.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - repo requirements include PyYAML.
    yaml = None  # type: ignore[assignment]

from simulation.tools import marker_registry

logger = logging.getLogger(__name__)

APPROVAL_VALUES = frozenset({"APPROVE", "ACCEPT", "APPROVE_WITH_CONDITIONS"})
SUSPICIOUS_COMMENT_MIN_CHARS = 50

_MARKER_TOKEN_RE = re.compile(r"^([A-Z][A-Z0-9_-]*):\s*(\S.*)?$", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^\s{0,3}```")
_INDENTED_CODE_RE = re.compile(r"^ {4,}\S")


@dataclass(frozen=True)
class MarkerHit:
    """One marker successfully parsed out of a body of text."""

    marker: str
    value: str
    action_id: str
    line_number: int
    raw_line: str
    extra_text: str = ""
    suspicious: bool = False


@dataclass(frozen=True)
class UnknownMarker:
    """A token that looked like a marker but is not in the registry."""

    token: str
    raw_line: str
    line_number: int


@dataclass(frozen=True)
class InvalidMarker:
    """A known marker whose value is outside the declared enum."""

    marker: str
    value: str
    raw_line: str
    line_number: int
    allowed_values: tuple[str, ...]


@dataclass
class ParseResult:
    """Outcome of parsing one body of text."""

    hits: list[MarkerHit] = field(default_factory=list)
    unknown: list[UnknownMarker] = field(default_factory=list)
    invalid: list[InvalidMarker] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unknown and not self.invalid


def _strip_code_blocks(body: str) -> list[tuple[int, str]]:
    """Return non-code lines paired with their original 1-based line number.

    Markdown rendering treats two structures as code:

    - Fenced blocks delimited by ``` ``` ``` (or ``~~~``). Anything between
      opening and closing fence is verbatim — we toggle ``in_fence`` and skip.
    - Indented blocks where the line begins with four or more spaces. These
      are common when humans paste example markers into a comment.

    Skipping code blocks is what prevents a documentation snippet like
    ``REVIEW-VERDICT: APPROVE`` from accidentally transitioning the loop. Line
    numbers from the original body are preserved so error messages can point
    a reviewer at the right line.
    """
    lines = body.splitlines()
    out: list[tuple[int, str]] = []
    in_fence = False
    for idx, line in enumerate(lines, start=1):
        if _CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _INDENTED_CODE_RE.match(line):
            continue
        out.append((idx, line))
    return out


def _index_specs() -> dict[str, marker_registry.MarkerSpec]:
    """Return marker name (upper) → spec, for O(1) lookup."""
    return {spec.marker.upper(): spec for spec in marker_registry.load_marker_specs().values()}


def parse_body(body: str, *, comment_length: int | None = None) -> ParseResult:
    """Parse all markers from ``body`` and classify them.

    ``comment_length`` lets callers pass the original comment length so the
    suspicious-approval heuristic can compare against the comment as a whole
    instead of just the marker line.
    """
    result = ParseResult()
    if not body:
        return result

    specs_by_marker = _index_specs()
    effective_length = comment_length if comment_length is not None else len(body)

    for line_no, raw_line in _strip_code_blocks(body):
        stripped = raw_line.strip()
        if not stripped or ":" not in stripped:
            continue
        match = _MARKER_TOKEN_RE.match(stripped)
        if not match:
            continue
        token = match.group(1).upper()
        remainder = (match.group(2) or "").strip()
        spec = specs_by_marker.get(token)
        if spec is None:
            result.unknown.append(
                UnknownMarker(token=token, raw_line=raw_line, line_number=line_no)
            )
            continue
        # Pull the first contiguous A-Z0-9_ word as the value; anything after
        # is treated as commentary (e.g. "ACCEPT because CI is green").
        value_match = re.match(r"([A-Z][A-Z0-9_]*)\s*(.*)$", remainder, re.IGNORECASE)
        if not value_match:
            result.invalid.append(
                InvalidMarker(
                    marker=spec.marker,
                    value="",
                    raw_line=raw_line,
                    line_number=line_no,
                    allowed_values=spec.values,
                )
            )
            continue
        value = value_match.group(1).upper()
        extra = value_match.group(2).strip()
        if spec.values and value not in spec.values:
            result.invalid.append(
                InvalidMarker(
                    marker=spec.marker,
                    value=value,
                    raw_line=raw_line,
                    line_number=line_no,
                    allowed_values=spec.values,
                )
            )
            continue
        if extra:
            warning = (
                f"line {line_no}: extra text after {spec.marker}: {value} "
                f"({extra!r}) — accepting marker, ignoring tail"
            )
            result.warnings.append(warning)
            logger.warning(warning)
        suspicious = (
            value in APPROVAL_VALUES
            and _short_comment(stripped, value, effective_length)
        )
        if suspicious:
            result.warnings.append(
                f"line {line_no}: short approval ({effective_length} chars) — flag for human confirmation"
            )
        result.hits.append(
            MarkerHit(
                marker=spec.marker,
                value=value,
                action_id=spec.action_id,
                line_number=line_no,
                raw_line=raw_line,
                extra_text=extra,
                suspicious=suspicious,
            )
        )
    return result


def _short_comment(marker_line: str, value: str, total_length: int) -> bool:
    """A comment counts as short if the prose around the marker is <50 chars.

    "I APPROVE" is suspiciously terse — somebody clicked through a UI without
    reading. The heuristic subtracts the length of the marker line itself
    (which an agent always types verbatim) and compares the remainder to a
    50-character minimum. Tunable via :data:`SUSPICIOUS_COMMENT_MIN_CHARS`.
    """
    return max(total_length - len(marker_line), 0) < SUSPICIOUS_COMMENT_MIN_CHARS


def valid_marker_strings() -> list[str]:
    """Return human-readable list of every valid ``MARKER: VALUE`` combination."""
    out: list[str] = []
    for spec in marker_registry.load_marker_specs().values():
        if not spec.values:
            out.append(f"{spec.marker}: <free-form>")
            continue
        for value in spec.values:
            out.append(f"{spec.marker}: {value}")
    return sorted(out)


def first_unknown_marker(results: Iterable[ParseResult]) -> UnknownMarker | None:
    """Return the first unknown marker across many parse results, if any."""
    for result in results:
        if result.unknown:
            return result.unknown[0]
    return None


# ---------------------------------------------------------------------------
# Action-output schema validation.
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / ".github" / "action-templates" / "schemas"

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema(action_name: str) -> dict[str, Any] | None:
    """Load and cache the schema file for an action, or None if missing."""
    if yaml is None:
        raise RuntimeError("PyYAML is required to load action schemas")
    if action_name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[action_name]
    path = SCHEMA_DIR / f"{action_name}.schema.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"schema for {action_name} is not a mapping")
    _SCHEMA_CACHE[action_name] = data
    return data


def reset_schema_cache() -> None:
    """Drop the schema cache; useful in tests that mutate schemas on disk."""
    _SCHEMA_CACHE.clear()


@dataclass
class SectionHit:
    heading: str
    start_line: int
    end_line: int
    body: str


def _extract_sections(text: str) -> dict[str, SectionHit]:
    """Index Markdown sections by lower-cased heading text.

    Recognises ``#``/``##`` ATX headings, bold ``**Heading:**`` lines, and
    bold ``**Heading**`` lines without trailing punctuation. The body of a
    section is everything from the line after the heading up to the next
    heading or the end of the document. Code blocks inside a section count
    toward its length.
    """
    lines = text.splitlines()
    sections: dict[str, SectionHit] = {}
    boundaries: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        heading: str | None = None
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
        else:
            match = re.match(r"^\*\*([^*]+?)\*\*\s*:?$", stripped)
            if match:
                heading = match.group(1).strip().rstrip(":")
        if heading:
            boundaries.append((idx, heading))
    for i, (line_idx, heading) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(lines)
        body = "\n".join(lines[line_idx + 1 : end]).strip()
        sections[heading.lower()] = SectionHit(
            heading=heading,
            start_line=line_idx + 1,
            end_line=end,
            body=body,
        )
    return sections


@dataclass
class ActionValidationResult:
    valid: bool
    missing_items: list[str]
    warnings: list[str]
    parse_result: ParseResult | None = None


def validate_action_output(
    action_name: str,
    output_text: str,
    issue_context: dict[str, Any] | None = None,
) -> ActionValidationResult:
    """Check that an agent's output satisfies the schema for ``action_name``.

    Validation steps:

    1. Schema must exist for the action (otherwise return invalid).
    2. Every ``required_marker`` must appear at least once and have a value in
       ``allowed_values`` (parsed via the strengthened :func:`parse_body`).
    3. Every ``required_section`` heading must exist (case-insensitive) and
       its body must have length >= ``min_length``.
    4. Suspicious approval and extra-text warnings from parsing are surfaced
       as warnings.
    """
    schema = _load_schema(action_name)
    if schema is None:
        return ActionValidationResult(
            valid=False,
            missing_items=[f"schema for action {action_name!r} not found"],
            warnings=[],
        )
    if not output_text or not output_text.strip():
        return ActionValidationResult(
            valid=False,
            missing_items=["output is empty"],
            warnings=[],
        )

    parse_result = parse_body(output_text, comment_length=len(output_text))
    missing: list[str] = []

    # Chain-of-Thought is required when the caller passes issue context
    # (which carries the body + labels needed to pick a complexity bucket).
    # Status-only actions and callers without context are skipped — the
    # latter keeps older tests/scripts that pre-date CoT working.
    if action_name not in {"post_status_and_exit", "skip"} and issue_context:
        from simulation.tools import loop_speedup  # lazy to avoid cycle

        ctx = issue_context
        labels = [label.get("name", "") for label in ctx.get("labels") or []]
        spec = loop_speedup.cot_requirements({"body": ctx.get("body") or "", "labels": ctx.get("labels") or []})
        if spec.get(loop_speedup.REQUIRE_COT_KEY, True):
            cot_ok, cot_msg = validate_cot(output_text, ctx.get("body") or "", labels)
            if not cot_ok:
                missing.append(cot_msg)

    required_markers = schema.get("required_markers") or []
    for entry in required_markers:
        marker = (entry.get("marker") or "").strip()
        if not marker:
            continue
        # YAML may coerce bare TRUE/FALSE/ON/OFF to bools — stringify defensively.
        allowed = [str(v).upper() for v in (entry.get("allowed_values") or [])]
        hits = [h for h in parse_result.hits if h.marker.upper() == marker.upper()]
        # Fall back to a direct regex when the schema lists a marker that is
        # not in markers.yml (e.g. orphan templates like discussion.md).
        if not hits:
            pattern = rf"(?im)^{re.escape(marker)}:\s*(?P<value>[A-Z][A-Z0-9_]+)"
            for match in re.finditer(pattern, output_text):
                pseudo = MarkerHit(
                    marker=marker,
                    value=match.group("value").upper(),
                    action_id=action_name,
                    line_number=output_text[: match.start()].count("\n") + 1,
                    raw_line=match.group(0),
                )
                hits.append(pseudo)
        if not hits:
            if allowed:
                missing.append(f"required marker `{marker}: {{{'|'.join(allowed)}}}` not found")
            else:
                missing.append(f"required marker `{marker}:` not found")
            continue
        if allowed and not any(hit.value in allowed for hit in hits):
            actual = ", ".join(sorted({hit.value for hit in hits}))
            missing.append(
                f"marker `{marker}:` has value {actual} but allowed values are {{{'|'.join(allowed)}}}"
            )

    # AC enforcement for the planning workflow's implementer step.
    if action_name == "implement_with_ac" and issue_context:
        ok, missing_acs = validate_acceptance_criteria(
            issue_context.get("body") or "", output_text
        )
        if not ok:
            missing.append(
                "implementation does not reference acceptance criteria: "
                + ", ".join(missing_acs)
            )

    required_sections = schema.get("required_sections") or []
    sections = _extract_sections(output_text)
    for entry in required_sections:
        heading = (entry.get("heading") or "").strip()
        min_length = int(entry.get("min_length") or 0)
        if not heading:
            continue
        hit = sections.get(heading.lower())
        if hit is None:
            missing.append(f"required section `{heading}` not found")
            continue
        if len(hit.body) < min_length:
            missing.append(
                f"section `{heading}` is {len(hit.body)} chars, need >= {min_length}"
            )

    warnings = list(parse_result.warnings)
    for hit in parse_result.hits:
        if hit.suspicious:
            warnings.append(
                f"Short approval on line {hit.line_number} — please confirm intentional"
            )
    if parse_result.invalid:
        for entry in parse_result.invalid:
            missing.append(
                f"marker `{entry.marker}: {entry.value}` is not in allowed enum {entry.allowed_values}"
            )

    return ActionValidationResult(
        valid=not missing,
        missing_items=missing,
        warnings=warnings,
        parse_result=parse_result,
    )


def extract_markers(body: str) -> list[MarkerHit]:
    """Return every marker found in ``body`` in order of appearance.

    Thin wrapper around :func:`parse_body` for callers that only need the
    list of hits and not the unknown/invalid/warnings sidebar.
    """
    return list(parse_body(body).hits)


_AC_LINE_RE = re.compile(r"^-\s*\[[\sx]\]\s*(AC\d+):\s*(.*)$", re.MULTILINE | re.IGNORECASE)


def validate_acceptance_criteria(issue_body: str, agent_output: str) -> tuple[bool, list[str]]:
    """Check that ``agent_output`` mentions every AC listed in ``issue_body``.

    An AC line in the issue body looks like ``- [ ] AC1: …``. The
    implementer must reference each AC id (``AC1``, ``AC2``…) somewhere
    in their output, or quote the AC text verbatim. Returns
    ``(all_present, missing_ids)``.
    """
    ac_lines = _AC_LINE_RE.findall(issue_body or "")
    missing: list[str] = []
    for ac_id, ac_text in ac_lines:
        if ac_id.lower() not in agent_output.lower() and (ac_text and ac_text.lower() not in agent_output.lower()):
            missing.append(ac_id)
    return not missing, missing


_CHAIN_NEXT_RE = re.compile(r"^CHAIN-NEXT:\s*(?P<action>[a-z][a-z0-9_]+)\s*$", re.MULTILINE | re.IGNORECASE)


def extract_chain_next(body: str) -> str | None:
    """Return the action id requested by ``CHAIN-NEXT:`` or ``None``.

    The marker must appear on its own line at the end of the body (or with
    only trailing whitespace after it). Action ids are lower-case
    underscore-separated identifiers. Matching is case-insensitive so
    "Chain-Next:" is also recognized; the returned id is normalised to
    lower-case.

    Only the *first* ``CHAIN-NEXT`` is returned; a body that emits two of
    them is treated as ambiguous by callers (the loop_runner refuses the
    chain and breaks). This keeps the chaining contract tight.
    """
    if not body:
        return None
    matches = list(_CHAIN_NEXT_RE.finditer(body))
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning("multiple CHAIN-NEXT markers found; refusing to chain")
        return None
    return matches[0].group("action").lower()


def detect_repeated_unknown_marker(
    bodies: Iterable[str],
) -> dict[str, int]:
    """Count occurrences of each unknown marker token across multiple bodies.

    Used by the orchestrator to enforce the "unknown marker twice → close"
    rule (#3 in the audit).
    """
    counts: dict[str, int] = {}
    for body in bodies:
        result = parse_body(body)
        for entry in result.unknown:
            counts[entry.token] = counts.get(entry.token, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Chain-of-Thought (CoT) extraction and validation.
# ---------------------------------------------------------------------------

_COT_HEADER_RE = re.compile(
    r"\*\*Reasoning:\*\*\s*(?P<body>.*?)(?=\n\s*\n[A-Z][A-Z-]+:|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_COT_STEP_RE = re.compile(
    r"^\s*(\d+)\.\s+(?P<text>.+?)(?=^\s*\d+\.\s+|\Z)",
    re.DOTALL | re.MULTILINE,
)


def extract_cot(output_text: str) -> str:
    """Return the text inside ``**Reasoning:**`` … (until blank line + marker)."""
    if not output_text:
        return ""
    match = _COT_HEADER_RE.search(output_text)
    return match.group("body").strip() if match else ""


def _parse_cot_steps(cot_text: str) -> list[str]:
    if not cot_text:
        return []
    out: list[str] = []
    for match in _COT_STEP_RE.finditer(cot_text + "\n"):
        out.append(match.group("text").strip())
    return out


def validate_cot(
    output_text: str,
    issue_body: str,
    labels: list[str] | tuple[str, ...],
) -> tuple[bool, str]:
    """Confirm the CoT section meets complexity-derived minimums.

    Returns ``(ok, message)``. On success ``message`` is ``"CoT valid"``;
    on failure it explains exactly which constraint failed so the next
    iteration can fix the right thing.
    """
    from simulation.tools import complexity as _complexity  # lazy to avoid cycle

    spec = _complexity.detect_complexity(issue_body, list(labels or []))
    min_steps = int(spec["min_steps"])
    min_words = int(spec["min_words_per_step"])
    cot_text = extract_cot(output_text)
    if not cot_text:
        return (
            False,
            f"Missing `**Reasoning:**` section with at least {min_steps} numbered steps.",
        )
    steps = _parse_cot_steps(cot_text)
    if len(steps) < min_steps:
        return False, f"Need at least {min_steps} reasoning steps, found {len(steps)}."
    for i, step in enumerate(steps, start=1):
        words = len(step.split())
        if words < min_words:
            return False, f"Step {i} has only {words} words (minimum {min_words})."
    return True, "CoT valid"
