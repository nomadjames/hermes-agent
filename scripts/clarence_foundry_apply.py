#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.clarence_foundry.apply import (  # noqa: E402
    FoundryApplyError,
    apply_candidate,
    build_apply_plan,
)


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clarence Foundry Phase 5 manual apply harness. It only creates a "
            "local application bundle after exact confirmation; it never writes "
            "memory, skills, vault, config, cron, git, GitHub, or public channels."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview_parser = subparsers.add_parser("preview", help="Build a manual apply plan without writing artifacts")
    preview_parser.add_argument("key", help="Candidate review key")
    preview_parser.add_argument("--json", action="store_true", help="Print full JSON plan")

    apply_parser = subparsers.add_parser("apply", help="Create a local application bundle after exact confirmation")
    apply_parser.add_argument("key", help="Candidate review key")
    apply_parser.add_argument("--confirm", required=True, help="Exact confirmation phrase from preview")
    apply_parser.add_argument("--json", action="store_true", help="Print full JSON result")
    return parser


def _common_args(args) -> dict:
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preview":
            plan = build_apply_plan(args.key, **_common_args(args))
            if args.json:
                _print_json({"success": True, "plan": plan})
            else:
                print(f"Candidate: {plan['key']}")
                print(f"Action: {plan['action']}")
                print(f"Application dir: {plan['application_dir']}")
                print(f"Candidate SHA256: {plan['candidate_sha256']}")
                print(f"Plan SHA256: {plan['plan_sha256']}")
                print(f"Confirmation phrase: {plan['confirmation_phrase']}")
                print("Writes:")
                for item in plan["writes"]:
                    print(f"- {item['mode']} {item['kind']}: {item['path']}")
            return 0
        if args.command == "apply":
            result = apply_candidate(args.key, confirm=args.confirm, **_common_args(args))
            if args.json:
                _print_json(result)
            else:
                application = result["application"]
                print("Phase 5 local application bundle created.")
                print(f"Application dir: {application['application_dir']}")
                print(f"Apply log result: {application['result']}")
            return 0
    except FoundryApplyError as exc:
        print(f"clarence_foundry_apply: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
