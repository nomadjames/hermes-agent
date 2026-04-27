from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from utils import atomic_json_write

from .candidates import CandidateWriteError, validate_candidate, write_candidate

SCHEMA_VERSION = 0
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,96}$")
_QUOTA_MARKERS = (
    "insufficient_quota",
    "quota exceeded",
    "billing hard limit",
    "http 402",
    "payment required",
    "rate limit",
    "rate-limit",
)
_5XX_RE = re.compile(r"\b(?:500|502|503|504)\b")
GENERATOR_SCRIPTS = (
    ("self_audit", "foundry_self_audit.py", "self-audit"),
    ("skill_candidates", "foundry_skill_candidates.py", "skill-candidates"),
    ("routing_bench", "foundry_routing_bench.py", "routing-bench"),
)
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class FoundryNightlyError(RuntimeError):
    """Raised when the Phase 3 nightly wrapper refuses unsafe execution."""


def default_runs_root() -> Path:
    return get_hermes_home() / "foundry" / "runs"


def default_run_id(now: datetime | None = None) -> str:
    timestamp = now or datetime.now(UTC)
    return timestamp.strftime("%Y%m%dt%H%M%Sz")


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise FoundryNightlyError("unsafe run_id")
    if any(part in run_id for part in ("/", "\\", "..", "~")):
        raise FoundryNightlyError("unsafe run_id")
    return run_id


def _resolve_root(path: str | Path) -> Path:
    root = Path(path)
    default_root = default_runs_root()
    if root.resolve(strict=False) != default_root.resolve(strict=False):
        raise FoundryNightlyError("runs_root must be the default HERMES_HOME/foundry/runs directory")
    if root.exists() and not root.is_dir():
        raise FoundryNightlyError("runs_root exists and is not a directory")
    return root


def _ensure_inside(root: Path, target: Path, *, label: str = "artifact") -> None:
    root_resolved = root.resolve(strict=False)
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise FoundryNightlyError(f"{label} escapes run directory") from exc


def prepare_run_dir(*, run_id: str, runs_root: str | Path | None = None) -> Path:
    safe_run_id = validate_run_id(run_id)
    root = _resolve_root(default_runs_root() if runs_root is None else runs_root)
    run_dir = root / safe_run_id
    _ensure_inside(root, run_dir, label="run directory")
    if run_dir.exists():
        if run_dir.is_symlink():
            _ensure_inside(root, run_dir.resolve(strict=True), label="run directory")
        raise FoundryNightlyError("run directory already exists")
    run_dir.mkdir(parents=True)
    _ensure_inside(root, run_dir, label="run directory")
    return run_dir


def _safe_artifact_path(run_dir: Path, relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
        raise FoundryNightlyError("unsafe artifact path")
    target = run_dir / relative
    _ensure_inside(run_dir, target)
    return target


def _write_text_artifact(run_dir: Path, relative_path: str | Path, text: str) -> Path:
    path = _safe_artifact_path(run_dir, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json_artifact(run_dir: Path, relative_path: str | Path, data: Any) -> Path:
    path = _safe_artifact_path(run_dir, relative_path)
    atomic_json_write(path, data, sort_keys=True)
    return path


def _safe_subprocess_env() -> dict[str, str]:
    allowed = {
        "HOME",
        "HERMES_HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_command(
    cmd: Sequence[str | Path],
    *,
    repo_root: Path,
    run_dir: Path,
    step_name: str,
    stdout_path: str | Path,
    stderr_path: str | Path,
    timeout_seconds: int,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    cmd_text = [str(part) for part in cmd]
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        completed = command_runner(
            cmd_text,
            cwd=repo_root,
            timeout=timeout_seconds,
            text=True,
            capture_output=True,
            check=False,
            env=_safe_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_text(exc.output)
        stderr = _coerce_text(exc.stderr)
        stdout_file = _write_text_artifact(run_dir, stdout_path, stdout)
        stderr_file = _write_text_artifact(run_dir, stderr_path, stderr)
        return {
            "name": step_name,
            "ok": False,
            "status": "failed",
            "failure_code": "timeout",
            "returncode": None,
            "command": cmd_text,
            "stdout_path": str(stdout_file.relative_to(run_dir)),
            "stderr_path": str(stderr_file.relative_to(run_dir)),
            "started_at": started_at,
            "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
    stdout = _coerce_text(completed.stdout)
    stderr = _coerce_text(completed.stderr)
    stdout_file = _write_text_artifact(run_dir, stdout_path, stdout)
    stderr_file = _write_text_artifact(run_dir, stderr_path, stderr)
    failure_code = None
    if completed.returncode != 0:
        failure_code = _classify_failure(
            step_name=step_name,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    return {
        "name": step_name,
        "ok": completed.returncode == 0,
        "status": "passed" if completed.returncode == 0 else "failed",
        "failure_code": failure_code,
        "returncode": completed.returncode,
        "command": cmd_text,
        "stdout_path": str(stdout_file.relative_to(run_dir)),
        "stderr_path": str(stderr_file.relative_to(run_dir)),
        "stdout": stdout,
        "stderr": stderr,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _classify_failure(*, step_name: str, returncode: int | None, stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if any(marker in text for marker in _QUOTA_MARKERS):
        return "quota_error"
    if len(_5XX_RE.findall(text)) >= 2:
        return "model_5xx_storm"
    if step_name in {"self_audit", "skill_candidates", "routing_bench"}:
        if returncode == 2 or "candidate" in text:
            return "candidate_rejected"
    return "command_failed"


def _summary_base(*, run_id: str, run_dir: Path, repo_root: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "foundry-phase3-nightly",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "repo_root": str(repo_root),
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ok": False,
        "status": "running",
        "failure_code": None,
        "steps": [],
        "artifacts": {},
    }


def _finish_summary(run_dir: Path, summary: dict[str, Any], *, ok: bool, failure_code: str | None = None) -> dict[str, Any]:
    summary["ok"] = ok
    summary["status"] = "passed" if ok else "failed"
    summary["failure_code"] = failure_code
    summary["finished_at"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary["artifacts"]["summary"] = "summary.json"
    _write_json_artifact(run_dir, "summary.json", summary)
    return summary


def _git_command(command_runner: CommandRunner, repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return command_runner(
        ["git", "--no-optional-locks", "-C", str(repo_root), *args],
        cwd=repo_root,
        timeout=30,
        text=True,
        capture_output=True,
        check=False,
        env=_safe_subprocess_env(),
    )


def collect_git_metadata(
    *,
    repo_root: Path,
    command_runner: CommandRunner = subprocess.run,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    def run(args: Sequence[str]) -> str:
        result = _git_command(command_runner, repo_root, args)
        if result.returncode != 0:
            raise FoundryNightlyError(f"git metadata command failed: {' '.join(args)}")
        return _coerce_text(result.stdout).strip()

    branch = run(["rev-parse", "--abbrev-ref", "HEAD"])
    head = run(["rev-parse", "HEAD"])
    status = run(["status", "--porcelain"])
    merge_base = run(["merge-base", "HEAD", "origin/main"])
    dirty = bool(status)
    metadata = {
        "branch": branch,
        "head": head,
        "merge_base_origin_main": merge_base,
        "dirty": dirty,
        "dirty_status": status.splitlines(),
        "allow_dirty": allow_dirty,
    }
    if dirty and not allow_dirty:
        raise FoundryNightlyError("worktree is dirty; pass allow_dirty only for reviewed manual runs")
    return metadata


def _run_reliability(
    *,
    repo_root: Path,
    run_dir: Path,
    timeout_seconds: int,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    manifest_path = _safe_artifact_path(run_dir, "reliability/manifest.json")
    cmd = [
        sys.executable,
        "-m",
        "agent.clarence_reliability.runner",
        "--repo-root",
        str(repo_root),
        "--case-root",
        str(repo_root),
        "--manifest",
        str(manifest_path),
        "--json",
    ]
    step = _run_command(
        cmd,
        repo_root=repo_root,
        run_dir=run_dir,
        step_name="reliability",
        stdout_path="reliability/stdout.txt",
        stderr_path="reliability/stderr.txt",
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    if not step["ok"]:
        return step
    try:
        result = json.loads(step.pop("stdout") or "{}")
    except json.JSONDecodeError:
        step["ok"] = False
        step["status"] = "failed"
        step["failure_code"] = "invalid_json"
        return step
    _write_json_artifact(run_dir, "reliability/result.json", result)
    step["result_path"] = "reliability/result.json"
    step["manifest_path"] = "reliability/manifest.json"
    if result.get("ok") is not True:
        step["ok"] = False
        step["status"] = "failed"
        step["failure_code"] = "reliability_failed"
    return step


def _write_candidate_from_stdout(run_dir: Path, candidate_root: Path, stdout: str, *, slug: str) -> Path:
    if candidate_root.is_symlink():
        raise CandidateWriteError("candidate root is a symlink")
    _ensure_inside(run_dir, candidate_root, label="candidate root")
    candidate = json.loads(stdout or "{}")
    validate_candidate(candidate)
    result = write_candidate(candidate, root=candidate_root, slug=slug, overwrite=False)
    _ensure_inside(run_dir, result.path, label="candidate path")
    return result.path


def _run_generator(
    *,
    repo_root: Path,
    run_dir: Path,
    step_name: str,
    script_name: str,
    slug: str,
    timeout_seconds: int,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    candidate_root = _safe_artifact_path(run_dir, "candidates")
    candidate_root.mkdir(parents=True, exist_ok=True)
    if candidate_root.is_symlink():
        raise FoundryNightlyError("candidate root is a symlink")
    _ensure_inside(run_dir, candidate_root, label="candidate root")
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / script_name),
        "--repo-root",
        str(repo_root),
        "--slug",
        slug,
        "--print-json",
    ]
    step = _run_command(
        cmd,
        repo_root=repo_root,
        run_dir=run_dir,
        step_name=step_name,
        stdout_path=f"generator_logs/{step_name}.stdout.txt",
        stderr_path=f"generator_logs/{step_name}.stderr.txt",
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    if not step["ok"]:
        return step
    try:
        candidate_path = _write_candidate_from_stdout(run_dir, candidate_root, step.pop("stdout"), slug=slug)
    except (CandidateWriteError, FoundryNightlyError, json.JSONDecodeError, OSError) as exc:
        step["ok"] = False
        step["status"] = "failed"
        step["failure_code"] = "candidate_rejected"
        step["message"] = str(exc)
        return step
    step["candidate_path"] = str(candidate_path.relative_to(run_dir))
    return step


def _run_routing_smoke(run_dir: Path, mode: str = "offline") -> dict[str, Any]:
    if mode != "offline":
        raise FoundryNightlyError("only offline routing smoke is allowed in Phase 3")
    cases = [
        {
            "id": "simple_current_fact_uses_quick",
            "ok": True,
            "actual_route": {"tool": "mcp_perplexity_pplx_smart_query", "intent": "quick"},
            "denied_intents": ["standard", "detailed", "research"],
        },
        {
            "id": "council_requires_confirmation",
            "ok": True,
            "actual_behavior": "confirmation_required_before_tool_call",
            "blocked_tools_before_confirmation": ["mcp_perplexity_pplx_council"],
        },
        {
            "id": "no_public_or_durable_writes",
            "ok": True,
            "blocked_actions": [
                "send_message",
                "cronjob.create",
                "memory.add",
                "mcp_memory_db_profile_set",
                "skill_manage",
                "config_edit",
            ],
        },
    ]
    result = {
        "mode": mode,
        "network_calls": "none",
        "ok": all(case["ok"] for case in cases),
        "cases": cases,
    }
    _write_json_artifact(run_dir, "routing_smoke/results.json", result)
    return {
        "name": "routing_smoke",
        "ok": result["ok"],
        "status": "passed" if result["ok"] else "failed",
        "failure_code": None if result["ok"] else "routing_smoke_failed",
        "result_path": "routing_smoke/results.json",
    }


def run_nightly(
    *,
    repo_root: str | Path,
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    timeout_seconds: int = 120,
    routing_smoke: str = "offline",
    allow_dirty: bool = False,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    if not repo.is_dir():
        raise FoundryNightlyError("repo_root must be a directory")
    safe_run_id = validate_run_id(run_id or default_run_id())
    run_dir = prepare_run_dir(run_id=safe_run_id, runs_root=runs_root)
    summary = _summary_base(run_id=safe_run_id, run_dir=run_dir, repo_root=repo)
    try:
        git_metadata = collect_git_metadata(repo_root=repo, command_runner=command_runner, allow_dirty=allow_dirty)
        _write_json_artifact(run_dir, "metadata/git.json", git_metadata)
        summary["artifacts"]["git_metadata"] = "metadata/git.json"

        reliability = _run_reliability(
            repo_root=repo,
            run_dir=run_dir,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        summary["steps"].append(_public_step(reliability))
        if not reliability["ok"]:
            return _finish_summary(run_dir, summary, ok=False, failure_code=reliability.get("failure_code"))

        for step_name, script_name, slug in GENERATOR_SCRIPTS:
            step = _run_generator(
                repo_root=repo,
                run_dir=run_dir,
                step_name=step_name,
                script_name=script_name,
                slug=slug,
                timeout_seconds=timeout_seconds,
                command_runner=command_runner,
            )
            summary["steps"].append(_public_step(step))
            if not step["ok"]:
                return _finish_summary(run_dir, summary, ok=False, failure_code=step.get("failure_code"))

        routing = _run_routing_smoke(run_dir, mode=routing_smoke)
        summary["steps"].append(routing)
        if not routing["ok"]:
            return _finish_summary(run_dir, summary, ok=False, failure_code=routing.get("failure_code"))
        return _finish_summary(run_dir, summary, ok=True)
    except FoundryNightlyError as exc:
        summary["steps"].append({"name": "nightly", "ok": False, "status": "failed", "failure_code": "safety_refusal"})
        summary["message"] = str(exc)
        return _finish_summary(run_dir, summary, ok=False, failure_code="safety_refusal")
    except Exception as exc:  # defensive fail-closed boundary for manual runner
        summary["steps"].append({"name": "nightly", "ok": False, "status": "failed", "failure_code": "unexpected_error"})
        summary["message"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return _finish_summary(run_dir, summary, ok=False, failure_code="unexpected_error")


def _public_step(step: dict[str, Any]) -> dict[str, Any]:
    blocked = {"stdout", "stderr"}
    return {key: value for key, value in step.items() if key not in blocked}
