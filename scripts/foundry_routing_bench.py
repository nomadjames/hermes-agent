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
        "bench_scope": "offline_expected_routes",
        "network_calls": "none",
        "cases": [
            {
                "id": "simple_current_fact_uses_quick",
                "prompt": "What is the current stable Python version?",
                "expected_route": {
                    "tool": "mcp_perplexity_pplx_smart_query",
                    "intent": "quick",
                },
                "denied_intents": ["standard", "detailed", "research"],
            },
            {
                "id": "council_requires_confirmation",
                "prompt": "Ask a model council about this.",
                "expected_behavior": "ask_for_confirmation_before_pro_queries",
            },
            {
                "id": "ollama_cloud_target_must_infer_before_promotion",
                "prompt": "Promote a new Ollama cloud model as a support coder.",
                "expected_behavior": "run tiny inference and a control model before trusting the route",
            },
        ],
        "blocked_actions": ["mcp_perplexity_pplx_smart_query", "mcp_perplexity_pplx_council", "ollama_api_call"],
        "repo_root_name": Path(repo_root).name,
    }
    return build_candidate_envelope(
        kind="routing_bench",
        title="Clarence routing bench proposal",
        summary="Report-only offline route expectations for later live routing benchmarks.",
        source="scripts/foundry_routing_bench.py",
        payload=payload,
        slug=slug,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a report-only Clarence routing bench candidate.")
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
        print(f"foundry_routing_bench: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
