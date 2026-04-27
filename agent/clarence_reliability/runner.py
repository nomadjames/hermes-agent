from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from .loader import discover_case_paths, load_cases
from .manifest import build_manifest, manifest_to_dict, write_manifest
from .schema import Case
from .trace import Trace
from .verifiers import Finding, VerifyContext, run_verifiers


class TraceAdapter(Protocol):
    name: str

    def collect(self, case: Case, context: VerifyContext) -> Trace: ...


class YamlTraceAdapter:
    name = "yaml-trace"

    def collect(self, case: Case, context: VerifyContext) -> Trace:
        return case.trace or Trace()


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    ok: bool
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class RunResult:
    ok: bool
    cases: tuple[CaseResult, ...]


def run_case(
    case: Case,
    *,
    repo_root: str | Path,
    case_root: str | Path,
    adapter: TraceAdapter | None = None,
) -> CaseResult:
    context = VerifyContext(repo_root=Path(repo_root), case_root=Path(case_root))
    trace = (adapter or YamlTraceAdapter()).collect(case, context)
    findings = tuple(run_verifiers(case, trace, context))
    blocking = [finding for finding in findings if finding.severity == "error"]
    return CaseResult(case_id=case.id, ok=not blocking, findings=findings)


def run_cases(
    cases: Iterable[Case],
    *,
    repo_root: str | Path,
    case_root: str | Path,
    adapter: TraceAdapter | None = None,
) -> RunResult:
    results = tuple(run_case(case, repo_root=repo_root, case_root=case_root, adapter=adapter) for case in cases)
    return RunResult(ok=all(result.ok for result in results), cases=results)


def _result_to_dict(result: RunResult) -> dict:
    return {
        "ok": result.ok,
        "cases": [
            {
                "case_id": case.case_id,
                "ok": case.ok,
                "findings": [
                    {
                        "verifier": finding.verifier,
                        "severity": finding.severity,
                        "message": finding.message,
                        "event_index": finding.event_index,
                        "details": dict(finding.details),
                    }
                    for finding in case.findings
                ],
            }
            for case in result.cases
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline Clarence reliability cases.")
    parser.add_argument("case_path", nargs="*", help="Case YAML file or directory. If omitted, no cases are loaded.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--case-root", default=".")
    parser.add_argument("--manifest", help="Optional manifest JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print JSON result instead of text summary.")
    args = parser.parse_args(argv)

    paths: list[Path] = []
    for raw_path in args.case_path:
        paths.extend(discover_case_paths(raw_path))
    if args.case_path:
        if not paths:
            print("No case YAML files found for supplied path(s).", file=sys.stderr)
            return 2
        cases = load_cases(paths)
    else:
        from .cases import load_builtin_cases

        cases = load_builtin_cases()
    result = run_cases(cases, repo_root=args.repo_root, case_root=args.case_root)
    if args.manifest:
        write_manifest(build_manifest(cases, case_root=Path(args.case_root)), args.manifest)
    if args.json:
        print(json.dumps(_result_to_dict(result), sort_keys=True, indent=2))
    else:
        from .report import format_run_result

        print(format_run_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
