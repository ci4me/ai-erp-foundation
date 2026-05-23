"""Meta-Sage — the framework reviewing itself.

Reads the operating-model docs, persona prompt files, recent PR activity,
and currently-open Themes, then dispatches Claude with a brutal-honesty
system prompt to produce a critique of the framework as a whole.

Outputs Markdown to stdout — pipe to a Discussion comment or save for
review at the next 30-day re-ratification window (per
``docs/amendment-policy.md``).

Costs
-----

Roughly $0.50–$2.00 per run depending on how many docs are read. Defaults
to claude-sonnet-4-6. Set ``--model claude-opus-4-7-1m`` for deeper
critique at higher cost.

Usage
-----

::

    ANTHROPIC_API_KEY=sk-... python -m simulation.tools.meta_sage
    ANTHROPIC_API_KEY=sk-... python -m simulation.tools.meta_sage \\
        --model claude-opus-4-7-1m \\
        --output critique.md

Why this exists
---------------

The 32 persona reviewers each see ONE PR at a time. None of them ever
read the WHOLE framework and ask "is the framework coherent? Is there
a load-bearing assumption that will collapse in 6 months?" Meta-Sage
fills that gap. Single-pass critique; no follow-on actions.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]


_ROOT = Path(__file__).resolve().parents[2]
_DOCS_DIR = _ROOT / "docs"
_PROMPTS_DIR = _ROOT / ".github" / "agent-prompts"

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4000

_SYSTEM_PROMPT = """\
You are Meta-Sage — a one-shot meta-reviewer of a multi-agent
AI-collaboration framework that uses GitHub as its operating substrate.
Your job is to read the framework's source documents and recent activity,
then deliver a brutal, specific, useful critique.

You are NOT a cheerleader. You are NOT a polite peer reviewer. Your
output is graded on:

1. **Specificity.** Cite file paths, persona names, PR numbers.
2. **Severity calibration.** Mix structural issues with surface nits.
3. **Falsifiability.** For each criticism, name evidence that would
   prove the criticism wrong.
4. **Novelty.** Don't repeat what the existing personas have already
   said in PR reviews. Find what they MISSED.

Forbidden:
- Generic praise ("solid foundation", "comprehensive approach")
- Suggestions that boil down to "more documentation"
- Bureaucratic process additions without explaining what they catch
- Recommendations to add yet another persona

Output structure (Markdown):

1. **Verdict** — one of: STRUCTURALLY SOUND | CALIBRATION NEEDED | LOAD-BEARING ASSUMPTION AT RISK | FUNDAMENTAL REWRITE REQUIRED
2. **The 3 things that will break in 6 months** — concrete failure modes
   with named root cause.
3. **The 3 things you LIKE that the personas don't articulate** —
   underappreciated strengths.
4. **What I would build next** — one concrete artifact + why.
5. **Falsifier** — what observation would change your verdict.
"""


def gather_context(*, recent_prs_n: int = 5) -> str:
    """Collect framework source material into one big string for Claude."""
    parts: list[str] = ["# Framework source material\n"]

    if _DOCS_DIR.is_dir():
        parts.append("## docs/\n")
        for path in sorted(_DOCS_DIR.glob("*.md")):
            parts.append(f"### `docs/{path.name}`\n\n```markdown\n{path.read_text()}\n```\n")

    if _PROMPTS_DIR.is_dir():
        parts.append("## .github/agent-prompts/\n")
        for path in sorted(_PROMPTS_DIR.glob("*.md")):
            parts.append(f"### `.github/agent-prompts/{path.name}`\n\n```markdown\n{path.read_text()}\n```\n")

    parts.append(_recent_pr_summary(recent_prs_n))
    return "\n".join(parts)


def _recent_pr_summary(n: int) -> str:
    if not shutil.which("gh"):
        return ""
    try:
        out = subprocess.check_output(
            ["gh", "pr", "list", "-R", "ci4me/ai-erp-foundation",
             "--state", "all", "--limit", str(n),
             "--json", "number,title,state,reviewDecision,body"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return ""
    return f"## Recent PRs ({n})\n\n```json\n{out}\n```\n"


def dispatch_critique(context: str, model: str) -> str:
    if anthropic is None:
        raise RuntimeError("anthropic SDK not installed; pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var required")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"{context}\n\n"
                f"---\n\n"
                f"Now produce your critique per the structure in the system prompt. "
                f"Be specific. Cite paths. Name personas. Find what the existing "
                f"reviewers missed."
            ),
        }],
    )
    return response.content[0].text if response.content else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--recent-prs", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true",
                        help="Gather context and print its size; do not call the API.")
    args = parser.parse_args()

    context = gather_context(recent_prs_n=args.recent_prs)

    if args.dry_run:
        print(f"context size: {len(context)} chars (~{len(context) // 4} tokens)", file=sys.stderr)
        print(context[:2000])
        print("\n[...truncated, --dry-run]")
        return 0

    try:
        critique = dispatch_critique(context, args.model)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    header = (
        f"# Meta-Sage critique — {args.model}\n\n"
        f"_Generated by `simulation/tools/meta_sage.py`. "
        f"Brutal-honesty system prompt; not a peer review._\n\n---\n\n"
    )
    payload = header + critique
    if args.output:
        args.output.write_text(payload)
        print(f"wrote critique ({len(critique)} chars) to {args.output}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
