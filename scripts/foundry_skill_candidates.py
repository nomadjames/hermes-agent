#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.clarence_foundry.candidates import CandidateWriteError, build_candidate_envelope, validate_candidate, write_candidate  # noqa: E402

def build_candidate(repo_root: Path, slug: str | None = None) -> dict:
    payload = {
        "candidate_source": "phase1_reliability_cases",
        "proposals": [
            {
                "id": "session-search-discipline",
                "proposed_skill_name": "clarence-session-search-discipline",
                "rationale": "Use prior session search before answering project-state questions, and state uncertainty when recall is empty.",
                "source_case_ids": [
                    "session_search.prior_project_state_required",
                    "session_search.empty_result_requires_uncertainty",
                ],
                "proposal_only": True,
                "review_required": True,
                "install_action": "none",
            },
            {
                "id": "durable-write-lane-discipline",
                "proposed_skill_name": "clarence-durable-write-lane-discipline",
                "rationale": "Keep user preference updates, profile facts, and live-state checks in the correct lanes.",
                "source_case_ids": [
                    "lane.profile_identity_uses_profile_get",
                    "lane.preference_update_uses_user_memory",
                    "lane.live_state_uses_terminal_not_profile",
                ],
                "proposal_only": True,
                "review_required": True,
                "install_action": "none",
            },
        ],
        "blocked_actions": ["skill_manage", "memory_write", "profile_set"],
        "repo_root_name": Path(repo_root).name,
    }
    return build_candidate_envelope(
        kind="skill_candidates",
        title="Clarence skill candidate proposals",
        summary="Report-only candidate skill ideas derived from Phase 1 reliability cases.",
        source="scripts/foundry_skill_candidates.py",
        payload=payload,
        slug=slug,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write report-only Clarence skill candidate proposals.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--slug", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args(argv)
    try:
        candidate = build_candidate(repo_root=args.repo_root, slug=args.slug)
        validate_candidate(candidate)
        if args.print_json:
            print(json.dumps(candidate, indent=2, sort_keys=True))
            return 0
        result = write_candidate(candidate, root=args.out_dir, slug=args.slug, overwrite=args.overwrite)
        print(result.path)
        return 0
    except CandidateWriteError as exc:
        print(f"foundry_skill_candidates: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
