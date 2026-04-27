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
    repo_root = Path(repo_root)
    payload = {
        "audit_scope": "offline_static_skeleton",
        "phase1_base": "6c413472",
        "checks": [
            {
                "id": "phase1_reliability_harness_present",
                "status": "manual_review",
                "evidence": [
                    "agent/clarence_reliability",
                    "tests/agent/test_clarence_reliability_phase1.py",
                ],
            },
            {
                "id": "phase2_report_only_boundary",
                "status": "manual_review",
                "assertion": "Foundry Phase 2 generators only write proposal candidates.",
            },
        ],
        "blocked_actions": [
            "memory_write",
            "skill_install",
            "profile_set",
            "cron_create",
            "config_edit",
        ],
        "repo_evidence_present": {
            "phase1_tests": (repo_root / "tests" / "agent" / "test_clarence_reliability_phase1.py").exists(),
            "phase1_package": (repo_root / "agent" / "clarence_reliability").exists(),
        },
    }
    return build_candidate_envelope(
        kind="self_audit",
        title="Clarence Foundry self-audit candidate",
        summary="Report-only offline checks for reviewing Foundry safety boundaries.",
        source="scripts/foundry_self_audit.py",
        payload=payload,
        slug=slug,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a report-only Clarence Foundry self-audit candidate.")
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
        print(f"foundry_self_audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
