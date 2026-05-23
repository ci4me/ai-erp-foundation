"""The dispatcher loop. Trivial wrapper that calls next_prompt.py forever.

For programmatic use (from a script or another tool). The VS Code agent
can simply call this one OR can run the equivalent shell loop directly:

::

    while true; do
        python -m simulation.tools.next_prompt --emit > /tmp/prompt.md
        # ... launch sub-agent with /tmp/prompt.md ...
        # (in VS Code: this is the human-in-the-loop pasting + reviewing)
    done

When used as a library, ``dispatch_once`` returns the next action's
prompt without actually launching a sub-agent — the caller is
responsible for the dispatch.

Why this is intentionally tiny
------------------------------

All intelligence lives in ``next_prompt.py``. The dispatcher's job is
just to **never stop calling it**. If you want to change priority logic,
edit ``next_prompt.py``, not this file.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Iterator


def dispatch_once(repo: str = "ci4me/ai-erp-foundation") -> str:
    """Return the next sub-agent prompt as a string. Does not launch."""
    result = subprocess.run(
        ["python", "-m", "simulation.tools.next_prompt", "--repo", repo, "--emit"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"next_prompt.py failed: {result.stderr.strip()}")
    return result.stdout


def dispatch_loop(repo: str, max_iterations: int | None = None) -> Iterator[str]:
    """Yield the next prompt forever (or up to max_iterations). Never stops on its own."""
    i = 0
    while max_iterations is None or i < max_iterations:
        yield dispatch_once(repo)
        i += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="ci4me/ai-erp-foundation")
    parser.add_argument("--once", action="store_true",
                        help="Resolve + print one prompt and exit.")
    parser.add_argument("--max", type=int, default=None,
                        help="Print N prompts (one per line of headers) and exit.")
    args = parser.parse_args()

    if args.once or args.max == 1:
        print(dispatch_once(args.repo))
        return 0

    for i, prompt in enumerate(dispatch_loop(args.repo, max_iterations=args.max)):
        print(f"=== Iteration {i + 1} ===\n{prompt}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
