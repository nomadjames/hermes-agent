from __future__ import annotations

from .runner import CaseResult, RunResult


def format_case_result(result: CaseResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [f"{status} {result.case_id}"]
    for finding in result.findings:
        lines.append(f"  - [{finding.severity}] {finding.verifier}: {finding.message}")
    return "\n".join(lines)


def format_run_result(result: RunResult) -> str:
    if not result.cases:
        return "No Clarence reliability cases ran."
    header = "Clarence reliability: PASS" if result.ok else "Clarence reliability: FAIL"
    return "\n".join([header, *(format_case_result(case) for case in result.cases)])
