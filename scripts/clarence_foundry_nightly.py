#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.clarence_foundry.nightly import FoundryNightlyError, run_nightly  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local-only Clarence Foundry Phase 3 nightly wrapper. "
            "Outputs remain local and generated candidates require review with scripts/clarence_foundry_review.py."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--routing-smoke", choices=["offline"], default="offline")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow a dirty worktree for reviewed manual smoke runs.")
    parser.add_argument("--json", action="store_true", help="Print the full summary JSON.")
    args = parser.parse_args(argv)
    try:
        summary = run_nightly(
            repo_root=args.repo_root,
            run_id=args.run_id,
            timeout_seconds=args.timeout_seconds,
            routing_smoke=args.routing_smoke,
            allow_dirty=args.allow_dirty,
        )
    except FoundryNightlyError as exc:
        print(f"clarence_foundry_nightly: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(summary["run_dir"])
        print(summary["status"])
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
