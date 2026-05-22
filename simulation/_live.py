"""Live-mode prompt regression — Anthropic SDK dispatch + verdict parsing.

Imported by ``run.py`` when ``MODE=live``. Kept in a separate module so
``run.py`` stays focused on orchestration and the (cheap) dry-run path.

Closes the ``run_live()`` ``NotImplementedError`` stub from PR #10 and
closes Prism's BLOCK condition 2 (behavioral regression gate) from
Discussion #2. Required by issue #11.

Cost model
----------

Every persona call is priced (input + output tokens) and tracked per
scenario. A per-scenario ceiling (``--max-cost-usd``) stops execution
early if exceeded — Cora (Cost Architect) requirement.

Allow-listed model pricing is conservative: unknown models fall back to
Opus pricing so cost is over-counted, not under-counted.

Hallucination detection
-----------------------

Heuristic: backtick-quoted code-symbol references in the persona response
that do not appear in the scenario's mock-PR diff are counted as
hallucinations. An allow-list of common framework terms is excluded.
This is intentionally imperfect — better-than-zero baseline; LLM-as-judge
is a future refinement.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: anthropic SDK not installed ({exc}).", file=sys.stderr)
    raise

import yaml


_ROOT = Path(__file__).resolve().parents[1]
_PROMPTS_DIR = _ROOT / ".github" / "agent-prompts"
_PREAMBLE_PATH = _PROMPTS_DIR / "_preamble.md"
_SCORECARDS_DIR = _ROOT / "simulation" / "scorecards"

# Pricing (USD per million tokens) — Anthropic public pricing as of 2026-05.
# Unknown models fall back to Opus (conservative over-count).
_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-7-1m": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}
_DEFAULT_MODEL = "claude-haiku-4-5"  # cheap default; persona file overrides
_DEFAULT_MAX_COST_PER_SCENARIO_USD = 0.50
_DEFAULT_MAX_TOKENS_PER_PERSONA = 4000

# Allow-listed identifiers — common framework terms that aren't hallucinations
# even when they don't appear in the diff text.
_HALLUCINATION_ALLOW_LIST: set[str] = {
    "phpstan", "PHPStan", "pytest", "phpcs", "PHPCS", "github", "GitHub",
    "ANTHROPIC_API_KEY", "NotImplementedError", "Acceptance", "Verdict",
    "PASS", "FAIL", "MISSING", "UNKNOWN", "REQUEST_CHANGES", "APPROVE",
    "BLOCKED", "CHANGELOG", "README", "true", "false", "null", "None",
    "self", "this", "TODO", "WIP",
}


@dataclass
class PersonaResult:
    """One persona's outcome on one scenario."""

    persona_id: str
    model: str
    verdict_expected: str
    verdict_actual: str | None
    verdict_match: bool
    must_catch: list[str]
    flaws_caught: list[str]
    flaws_missed: list[str]
    hallucinations: list[str]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    raw_response: str


@dataclass
class LiveScenarioResult:
    """Aggregate outcome across all personas of one scenario."""

    scenario_id: str
    passed: bool
    personas: list[PersonaResult]
    total_cost_usd: float
    failure_reasons: list[str] = field(default_factory=list)


def create_client() -> "anthropic.Anthropic":
    """Build an Anthropic client; requires ANTHROPIC_API_KEY in env."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY env var required for live mode")
    return anthropic.Anthropic(api_key=key)


def load_persona_prompt(persona_id: str) -> tuple[str, dict[str, Any]]:
    """Read a persona file. Returns ``(system_prompt, frontmatter_dict)``."""
    path = _PROMPTS_DIR / f"{persona_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"persona prompt missing: {path}")
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return text, {}
    frontmatter = yaml.safe_load(match.group(1)) or {}
    return match.group(2).strip(), frontmatter


def load_preamble() -> str:
    """Return the Universal Reviewer Preamble text (or empty string)."""
    if not _PREAMBLE_PATH.is_file():
        return ""
    return _PREAMBLE_PATH.read_text()


def build_scenario_message(scenario: dict[str, Any], inherits_preamble: bool) -> str:
    """Compose the user message for a persona reviewing this scenario."""
    preamble = load_preamble() if inherits_preamble else ""
    diff = scenario["mock_pr"]["diff"]
    body = scenario["mock_pr"]["body"]
    title = scenario["mock_pr"]["title"]
    return (
        f"{preamble}\n\n"
        f"# Mock PR under review\n\n"
        f"**Title:** {title}\n\n"
        f"**Body:**\n\n{body}\n\n"
        f"**Diff (this is the COMPLETE content of the PR):**\n\n"
        f"```diff\n{diff}\n```\n\n"
        f"Apply your persona instructions to review this PR. Return a "
        f"structured review comment with your verdict and findings."
    )


def extract_verdict(text: str) -> str | None:
    """Find the first ``Verdict: X`` in the response. Normalize dashes to underscores."""
    pattern = re.compile(
        r"\*\*Verdict:?\*\*\s*([A-Z_]+(?:[-_/][A-Z_]+)*)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        match = re.search(r"\bVerdict:\s*([A-Z_]+(?:[-_/][A-Z_]+)*)", text, re.IGNORECASE)
    if match:
        normalized = match.group(1).upper().replace("-", "_").replace("/", "_")
        return normalized
    return None


def flaw_mentioned(flaw: dict[str, Any], text: str) -> bool:
    """Return True if a planted flaw is detected in the persona response.

    Two strategies (either is sufficient):
      1. The flaw ID is named directly (``F1``).
      2. Distinctive keywords from the flaw name appear (≥ 2 or majority).
    """
    if flaw["id"] in text:
        return True
    text_lower = text.lower()
    stop = {"the", "and", "for", "with", "from", "into", "but", "not", "are", "via"}
    keywords = [w for w in flaw["name"].lower().split() if len(w) > 3 and w not in stop]
    if not keywords:
        return False
    matches = sum(1 for w in keywords if w in text_lower)
    threshold = max(2, len(keywords) // 2)
    return matches >= threshold


def count_hallucinations(text: str, diff: str) -> list[str]:
    """Identifiers in backticks that don't appear in the diff (filtered by allow-list)."""
    candidates = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]+(?:\([^)]*\))?)`", text))
    diff_lower = diff.lower()
    hallucinations: list[str] = []
    for candidate in candidates:
        bare = candidate.split("(")[0]
        if bare in _HALLUCINATION_ALLOW_LIST:
            continue
        if bare.lower() not in diff_lower and len(bare) >= 4:
            hallucinations.append(candidate)
    return sorted(set(hallucinations))


def model_pricing(model: str) -> dict[str, float]:
    """Lookup pricing for a model id; fall back to Opus (conservative)."""
    return _PRICING.get(model, _PRICING["claude-opus-4-7"])


def compute_cost(tokens_in: int, tokens_out: int, model: str) -> float:
    """Compute USD cost given token counts and the model's pricing."""
    price = model_pricing(model)
    return (tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000


def dispatch_persona(
    client: Any,
    persona_id: str,
    persona_spec: dict[str, Any],
    scenario: dict[str, Any],
    max_tokens: int = _DEFAULT_MAX_TOKENS_PER_PERSONA,
) -> PersonaResult:
    """Call Anthropic for one persona × one scenario and parse the response."""
    system_prompt, frontmatter = load_persona_prompt(persona_id)
    model = persona_spec.get("model_override") or frontmatter.get("model_default", _DEFAULT_MODEL)
    inherits = bool(frontmatter.get("inherits_preamble", True))
    user_message = build_scenario_message(scenario, inherits)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = response.content[0].text if response.content else ""
    verdict = extract_verdict(text)
    diff = scenario["mock_pr"]["diff"]
    caught = [flaw["id"] for flaw in scenario["planted_flaws"] if flaw_mentioned(flaw, text)]
    missed = [fid for fid in persona_spec["must_catch"] if fid not in caught]
    hallucinations = count_hallucinations(text, diff)
    cost = compute_cost(response.usage.input_tokens, response.usage.output_tokens, model)

    return PersonaResult(
        persona_id=persona_id,
        model=model,
        verdict_expected=persona_spec["expected_verdict"],
        verdict_actual=verdict,
        verdict_match=verdict == persona_spec["expected_verdict"],
        must_catch=list(persona_spec["must_catch"]),
        flaws_caught=caught,
        flaws_missed=missed,
        hallucinations=hallucinations,
        tokens_in=response.usage.input_tokens,
        tokens_out=response.usage.output_tokens,
        cost_usd=cost,
        raw_response=text,
    )


def evaluate_scenario(
    client: Any,
    scenario: dict[str, Any],
    max_cost_per_scenario_usd: float = _DEFAULT_MAX_COST_PER_SCENARIO_USD,
) -> LiveScenarioResult:
    """Run all personas for one scenario and compute pass/fail per scenario."""
    persona_results: list[PersonaResult] = []
    total_cost = 0.0

    for persona_spec in scenario["personas"]:
        persona_result = dispatch_persona(client, persona_spec["id"], persona_spec, scenario)
        persona_results.append(persona_result)
        total_cost += persona_result.cost_usd
        if total_cost > max_cost_per_scenario_usd:
            return LiveScenarioResult(
                scenario_id=scenario["id"],
                passed=False,
                personas=persona_results,
                total_cost_usd=total_cost,
                failure_reasons=[
                    f"cost ceiling exceeded ({total_cost:.4f} > {max_cost_per_scenario_usd}) — stopping early"
                ],
            )

    return _assess_pass_criteria(scenario, persona_results, total_cost)


def _assess_pass_criteria(
    scenario: dict[str, Any],
    persona_results: list[PersonaResult],
    total_cost: float,
) -> LiveScenarioResult:
    """Apply the scenario's pass_threshold to compute the overall verdict."""
    threshold = scenario["pass_threshold"]
    failures: list[str] = []

    all_flaws = {flaw["id"] for flaw in scenario["planted_flaws"]}
    caught: set[str] = set()
    for persona_result in persona_results:
        caught.update(persona_result.flaws_caught)
    caught_pct = (len(caught) / len(all_flaws) * 100) if all_flaws else 100.0
    if caught_pct < threshold["flaws_caught_pct"]:
        failures.append(
            f"flaws_caught_pct {caught_pct:.0f}% < threshold {threshold['flaws_caught_pct']}%"
        )

    total_hallucinations = sum(len(p.hallucinations) for p in persona_results)
    if total_hallucinations > threshold["hallucinations_allowed"]:
        failures.append(
            f"hallucinations {total_hallucinations} > allowed {threshold['hallucinations_allowed']}"
        )

    if threshold["per_persona_verdict_match"]:
        mismatches = [p.persona_id for p in persona_results if not p.verdict_match]
        if mismatches:
            failures.append(f"verdict mismatch for: {mismatches}")

    return LiveScenarioResult(
        scenario_id=scenario["id"],
        passed=not failures,
        personas=persona_results,
        total_cost_usd=total_cost,
        failure_reasons=failures,
    )


def write_scorecard(persona_result: PersonaResult, scenario_id: str) -> None:
    """Append-update the persona's scorecard JSON with this scenario's run."""
    _SCORECARDS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCORECARDS_DIR / f"{persona_result.persona_id}.json"
    data: dict[str, Any] = {"persona_id": persona_result.persona_id, "scenarios": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text()) or data
        except json.JSONDecodeError:
            pass

    data.setdefault("scenarios", {})[scenario_id] = {
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": persona_result.model,
        "verdict_expected": persona_result.verdict_expected,
        "verdict_actual": persona_result.verdict_actual,
        "verdict_matched": persona_result.verdict_match,
        "flaws_must_catch": persona_result.must_catch,
        "flaws_caught": persona_result.flaws_caught,
        "flaws_missed": persona_result.flaws_missed,
        "hallucinations": persona_result.hallucinations,
        "tokens_in": persona_result.tokens_in,
        "tokens_out": persona_result.tokens_out,
        "cost_usd": round(persona_result.cost_usd, 4),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def run(
    scenarios_paths: list[Path],
    max_cost_per_scenario_usd: float = _DEFAULT_MAX_COST_PER_SCENARIO_USD,
) -> list[LiveScenarioResult]:
    """Main entry point for live regression. Returns one result per scenario."""
    client = create_client()
    results: list[LiveScenarioResult] = []
    for path in scenarios_paths:
        with path.open() as fh:
            scenario = yaml.safe_load(fh)
        result = evaluate_scenario(client, scenario, max_cost_per_scenario_usd=max_cost_per_scenario_usd)
        for persona_result in result.personas:
            write_scorecard(persona_result, result.scenario_id)
        results.append(result)
    return results
