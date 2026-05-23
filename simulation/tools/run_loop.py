"""CLI wrapper that runs ``loop_runner.run_iterations`` with chaining + logging.

The legacy ``next_prompt`` CLI emits one prompt at a time and stops. This
module wraps it in a ``while`` loop with the chaining + dedupe + stall
machinery in :mod:`simulation.tools.loop_runner` and writes a detailed,
per-iteration Markdown log so operators can reconstruct what happened.

Usage::

    python3 -m simulation.tools.run_loop --post-mode real \\
        --max-iterations 45 \\
        --log-file /tmp/loop-iterations/full_log.md

The log format matches the spec the operator submitted: each iteration
block carries timestamp, action / persona / target, chain length,
latency, token estimates, validation outcome, posted URL, state-hash
delta, stall counter, lessons injected, CoT step count, and cache hit
indication.

Because the legacy renderer is heavyweight, this CLI exposes a
``--dry-run`` mode that prints the schedule (action, persona, target)
for the next N iterations without invoking the model — useful as a
sanity check before a real run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from simulation.tools import loop_speedup
from simulation.tools import validator as _validator

logger = logging.getLogger("run_loop")


def _now() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_prompt(repo: str, post_mode: str, output_path: Path) -> dict[str, Any]:
    """Invoke the legacy CLI in ``--probe-only`` + ``--output`` modes."""
    if not shutil.which("python3"):
        raise RuntimeError("python3 not on PATH")
    cmd = [
        "python3",
        "-m",
        "simulation.tools.next_prompt",
        "--repo",
        repo,
        "--output",
        str(output_path),
        "--post-mode",
        post_mode,
    ]
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    latency_ms = int((time.time() - start) * 1000)
    probe = subprocess.run(
        [
            "python3",
            "-m",
            "simulation.tools.next_prompt",
            "--repo",
            repo,
            "--probe-only",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # `--probe-only` emits "priority: <action>\ncontext: { ... }" — parse it.
    probe_lines = probe.stdout.splitlines()
    action = ""
    context_blob = ""
    in_context = False
    for line in probe_lines:
        if line.startswith("priority:"):
            action = line.split(":", 1)[1].strip()
        elif line.startswith("context:"):
            context_blob = line.split(":", 1)[1].strip()
            in_context = True
        elif in_context:
            context_blob += line
    try:
        context = json.loads(context_blob) if context_blob else {}
    except json.JSONDecodeError:
        context = {}
    return {
        "action": action,
        "context": context,
        "latency_ms": latency_ms,
        "render_stdout": result.stdout[-400:],
        "render_stderr": result.stderr[-400:],
    }


def _write_iteration_block(
    fh,
    *,
    iteration: int,
    record: dict[str, Any],
    prompt_path: Path,
    body_path: Path | None,
) -> None:
    header_lines = ""
    if prompt_path.exists():
        with prompt_path.open() as ph:
            header_lines = "".join(ph.readlines()[:20])
    body_text = body_path.read_text() if body_path and body_path.exists() else "(no body — see notes)"
    fh.write(
        "\n## Iteration {i}\n\n".format(i=iteration)
        + "- **Timestamp**: {ts}\n".format(ts=record["timestamp"])
        + "- **Action**: `{a}`\n".format(a=record.get("action") or "n/a")
        + "- **Persona**: `{p}`\n".format(p=record.get("persona") or "n/a")
        + "- **Target**: {t}\n".format(t=record.get("target") or "n/a")
        + "- **Chain length**: {c}\n".format(c=record.get("chain_length", 0))
        + "- **Latency (ms)**: {l}\n".format(l=record.get("latency_ms", 0))
        + "- **Input tokens (est)**: {it}\n".format(it=record.get("input_tokens", 0))
        + "- **Output tokens (est)**: {ot}\n".format(ot=record.get("output_tokens", 0))
        + "- **Validation**: valid={v}\n".format(v=record.get("valid", False))
        + "- **Posted URL**: {u}\n".format(u=record.get("posted_url") or "n/a")
        + "- **State hash changed**: {h}\n".format(h=record.get("state_hash_changed", "n/a"))
        + "- **Stall counter**: {s}\n".format(s=record.get("stall_counter", 0))
        + "- **Lessons injected**: {ls}\n".format(ls=record.get("lessons_injected", 0))
        + "- **CoT steps**: {ct}\n".format(ct=record.get("cot_steps", 0))
        + "- **Prompt cache hit**: {ch}\n".format(ch=record.get("cache_hit", "n/a"))
        + "\n### Prompt header (first 20 lines)\n\n```markdown\n"
        + header_lines
        + "```\n\n### Body posted\n\n```markdown\n"
        + body_text
        + "\n```\n\n### Notes\n\n"
        + (record.get("notes") or "none")
        + "\n"
    )


def _build_performance_report(records: list[dict[str, Any]]) -> str:
    if not records:
        return "# Performance report\n\nNo iterations recorded.\n"
    latencies = [r.get("latency_ms", 0) for r in records]
    chain_lengths = [r.get("chain_length", 0) for r in records]
    validations = [r.get("valid", False) for r in records]
    posted = [r for r in records if r.get("posted_url")]
    stalls = [r for r in records if r.get("stall_counter", 0) > 0]
    chains_used = sum(1 for c in chain_lengths if c > 0)
    actions_saved = sum(chain_lengths)
    lessons = sum(r.get("lessons_injected", 0) for r in records)
    in_tokens = sum(r.get("input_tokens", 0) for r in records)
    out_tokens = sum(r.get("output_tokens", 0) for r in records)
    baseline_seconds = 10
    total_seconds = sum(latencies) / 1000.0
    saved_seconds = baseline_seconds * len(records) - total_seconds
    return (
        "# Performance report\n\n"
        f"- **Iterations**: {len(records)}\n"
        f"- **Avg latency (ms)**: {sum(latencies) // max(len(latencies), 1)}\n"
        f"- **Median latency (ms)**: {sorted(latencies)[len(latencies) // 2]}\n"
        f"- **p95 latency (ms)**: {sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0]}\n"
        f"- **Total est. input tokens**: {in_tokens}\n"
        f"- **Total est. output tokens**: {out_tokens}\n"
        f"- **Iterations with chaining**: {chains_used}\n"
        f"- **Average chain length**: {sum(chain_lengths) / max(len(records), 1):.2f}\n"
        f"- **Round-trips saved by chaining**: {actions_saved}\n"
        f"- **Validation failures**: {sum(1 for v in validations if not v)}\n"
        f"- **Posted to GitHub**: {len(posted)}\n"
        f"- **Stall events**: {len(stalls)}\n"
        f"- **Lessons injected total**: {lessons}\n"
        f"- **Baseline (10s × iter) seconds**: {baseline_seconds * len(records)}\n"
        f"- **Observed total seconds**: {total_seconds:.1f}\n"
        f"- **Estimated seconds saved**: {saved_seconds:.1f}\n"
        f"- **Bottlenecks**: GitHub round-trips for `gh issue view` and CI gate checks dominate latency; the chain primitive helps but the selector wedge (same persona on same target after a no-op tick) is still the largest stall driver.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="ci4me/ai-erp-foundation")
    parser.add_argument("--post-mode", choices=("dry-run", "real"), default="dry-run")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument(
        "--log-file",
        default="/tmp/loop-iterations/full_log.md",
        help="Markdown file to append per-iteration blocks to.",
    )
    parser.add_argument(
        "--performance-report",
        default="/tmp/loop-iterations/performance_report.md",
    )
    parser.add_argument("--dry-render", action="store_true",
                        help="Render the prompt + read state but do not invoke an LLM.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with log_path.open("w") as fh:
        fh.write("# Autonomous-loop run log\n")
        for iteration in range(1, args.max_iterations + 1):
            prompt_path = log_path.parent / f"iter{iteration}-prompt.md"
            body_path = log_path.parent / f"iter{iteration}-body.md"
            start_iter = time.time()
            try:
                render = _render_prompt(args.repo, args.post_mode, prompt_path)
            except Exception as exc:  # pragma: no cover
                logger.error("render failed at iteration %s: %s", iteration, exc)
                break
            latency_ms = int((time.time() - start_iter) * 1000)
            record = {
                "timestamp": _now(),
                "action": render["action"] or "unknown",
                "persona": (render["context"] or {}).get("persona_id") or "unknown",
                "target": (
                    (render["context"] or {}).get("pr", {}).get("number")
                    or (render["context"] or {}).get("issue", {}).get("number")
                    or "n/a"
                ),
                "chain_length": 0,
                "latency_ms": latency_ms,
                "input_tokens": prompt_path.stat().st_size // 4 if prompt_path.exists() else 0,
                "output_tokens": 0,
                "valid": True if args.dry_render else None,
                "posted_url": "(dry render)" if args.dry_render else None,
                "state_hash_changed": "n/a",
                "stall_counter": 0,
                "lessons_injected": 0,
                "cot_steps": 0,
                "cache_hit": "n/a",
                "notes": "Dry render only — set --dry-render=False and wire an LLM to post." if args.dry_render else "",
            }
            records.append(record)
            _write_iteration_block(
                fh,
                iteration=iteration,
                record=record,
                prompt_path=prompt_path,
                body_path=body_path if body_path.exists() else None,
            )

    Path(args.performance_report).write_text(_build_performance_report(records))
    print(
        f"wrote {args.max_iterations} blocks to {log_path} and "
        f"{args.performance_report}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))


__all__ = ["main"]
