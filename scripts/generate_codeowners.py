#!/usr/bin/env python3
"""Write ``.github/CODEOWNERS`` from persona frontmatter.

Delegates to :func:`simulation.tools.persona_registry.generate_codeowners`,
which only emits rules for personas declaring real ``github_handle`` +
``owns_paths`` (so the file stays header-only until that data exists).

Usage:
    python3 scripts/generate_codeowners.py            # write .github/CODEOWNERS
    python3 scripts/generate_codeowners.py --print     # print to stdout only
"""

from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from simulation.tools.persona_registry import generate_codeowners  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate .github/CODEOWNERS.")
    parser.add_argument("--print", action="store_true", help="Print only; do not write.")
    args = parser.parse_args(argv)

    content = generate_codeowners(repo_root=_PROJECT_ROOT)
    if args.print:
        print(content, end="")
        return 0

    target = os.path.join(_PROJECT_ROOT, ".github", "CODEOWNERS")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    rules = sum(1 for line in content.splitlines() if line and not line.startswith("#"))
    print(f"Wrote {target} ({rules} ownership rule(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
