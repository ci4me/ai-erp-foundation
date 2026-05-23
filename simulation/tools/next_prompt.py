"""CLI entrypoint for the autonomous-loop next prompt scheduler."""

from __future__ import annotations

import sys

from simulation.tools.next_prompt_cli import main


if __name__ == "__main__":
    sys.exit(main())
