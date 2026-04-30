#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.clarence_foundry.review import (  # noqa: E402
    FoundryReviewError,
    build_paused_local_cron_manifest,
    get_candidate,
    list_candidates,
    record_review,
    render_apply_prompt,
)


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local-only Clarence Foundry Phase 4 review helper. "
            "It records review decisions but never applies candidates or delivers publicly."
        )
    )
    parser.add_argument("--runs-root", help="Optional Foundry runs root; defaults to HERMES_HOME/foundry/runs")
    parser.add_argument(
        "--candidates-root",
        help="Optional standalone candidates root; defaults to HERMES_HOME/foundry/candidates",
    )
    parser.add_argument(
        "--review-log",
        help="Optional review log path; defaults to HERMES_HOME/foundry/reviews/review_log.jsonl",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List local candidate proposals")
    list_parser.add_argument("--json", action="store_true", help="Print JSON")
    list_parser.add_argument("--unreviewed", action="store_true", help="Hide candidates that already have a review event")

    show_parser = subparsers.add_parser("show", help="Show one candidate proposal")
    show_parser.add_argument("key", help="Candidate review key")
    show_parser.add_argument("--json", action="store_true", help="Print JSON")

    approve_parser = subparsers.add_parser("approve", help="Record approval for manual handling; does not apply")
    approve_parser.add_argument("key", help="Candidate review key")
    approve_parser.add_argument("--reviewer", required=True, help="Reviewer name")
    approve_parser.add_argument("--note", default="", help="Optional review note")

    reject_parser = subparsers.add_parser("reject", help="Record rejection; leaves candidate auditable")
    reject_parser.add_argument("key", help="Candidate review key")
    reject_parser.add_argument("--reviewer", required=True, help="Reviewer name")
    reject_parser.add_argument("--note", default="", help="Optional review note")

    apply_parser = subparsers.add_parser("apply-prompt", help="Print a manual normal-session prompt for one candidate")
    apply_parser.add_argument("key", help="Candidate review key")

    manifest_parser = subparsers.add_parser(
        "paused-cron-manifest",
        help="Print a paused local cron manifest; does not install or schedule it",
    )
    manifest_parser.add_argument("--workdir", required=True, help="Absolute repo workdir for the future cron job")
    manifest_parser.add_argument("--schedule", default="10 2 * * *", help="Cron schedule to include in the manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    common = {
        "runs_root": args.runs_root,
        "candidates_root": args.candidates_root,
        "review_log_path": args.review_log,
    }
    try:
        if args.command == "list":
            data = list_candidates(include_reviewed=not args.unreviewed, **common)
            if args.json:
                _print_json({"success": True, "count": len(data), "candidates": data})
            else:
                if not data:
                    print("No local Foundry candidates found.")
                for item in data:
                    status = "invalid" if not item["valid"] else (item.get("latest_review") or {}).get("decision", "unreviewed")
                    print(f"{item['key']}  [{status}]  {item['title']}")
            return 0
        if args.command == "show":
            data = get_candidate(args.key, **common)
            if args.json:
                _print_json({"success": True, "candidate": data})
            else:
                print(f"Key: {data['key']}")
                print(f"Title: {data['title']}")
                print(f"Kind: {data['kind']}")
                print(f"Path: {data['path']}")
                print(f"Valid: {data['valid']}")
                print(f"Latest review: {data['latest_review']}")
                print(f"Summary: {data['summary']}")
            return 0
        if args.command in {"approve", "reject"}:
            event = record_review(
                args.key,
                decision="approved" if args.command == "approve" else "rejected",
                reviewer=args.reviewer,
                note=args.note,
                **common,
            )
            _print_json({"success": True, "review": event})
            return 0
        if args.command == "apply-prompt":
            print(render_apply_prompt(args.key, **common))
            return 0
        if args.command == "paused-cron-manifest":
            _print_json({"success": True, "manifest": build_paused_local_cron_manifest(workdir=args.workdir, schedule=args.schedule)})
            return 0
    except FoundryReviewError as exc:
        print(f"clarence_foundry_review: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
