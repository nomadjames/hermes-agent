from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from .candidates import CandidateWriteError, validate_candidate
from .review import (
    FoundryReviewError,
    candidate_file_fingerprint,
    default_review_log_path,
    default_reviews_dir,
    get_candidate,
)

SCHEMA_VERSION = 0
PLAN_SCHEMA_VERSION = 0
BLOCKED_ACTIONS = (
    "memory_write",
    "skill_write",
    "vault_write",
    "config_edit",
    "cron_create",
    "cron_resume",
    "git_commit",
    "git_push",
    "github_comment",
    "public_delivery",
    "candidate_instruction_execution",
)
_SAFE_SEGMENT_RE = re.compile(r"^[a-z0-9._-]{1,180}$")


class FoundryApplyError(ValueError):
    """Raised when Phase 5 manual application would violate safety policy."""


def default_applications_root() -> Path:
    return get_hermes_home() / "foundry" / "applications"


def default_apply_log_path() -> Path:
    return default_reviews_dir() / "apply_log.jsonl"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _application_segment(key: str) -> str:
    readable = re.sub(r"[^a-z0-9._-]+", "-", key.lower()).strip("-._") or "candidate"
    readable = readable[:120].strip("-._") or "candidate"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    segment = f"{readable}-{digest}"
    if not _SAFE_SEGMENT_RE.fullmatch(segment):
        raise FoundryApplyError("unsafe candidate application segment")
    return segment


def _ensure_inside(root: Path, target: Path, *, message: str) -> None:
    root_resolved = root.resolve(strict=False)
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise FoundryApplyError(message) from exc


def _normalize_applications_root(applications_root: str | Path | None = None) -> Path:
    root = Path(applications_root) if applications_root is not None else default_applications_root()
    root = root.expanduser()
    canonical_root = default_applications_root().resolve(strict=False)
    _ensure_inside(
        canonical_root,
        root,
        message="application root must stay under HERMES_HOME/foundry/applications",
    )
    if root.exists():
        if root.is_symlink():
            raise FoundryApplyError("application root must not be a symlink")
        if not root.is_dir():
            raise FoundryApplyError("application root exists and is not a directory")
    return root


def _normalize_apply_log_path(apply_log_path: str | Path | None = None) -> Path:
    path = Path(apply_log_path) if apply_log_path is not None else default_apply_log_path()
    path = path.expanduser()
    canonical_path = default_apply_log_path().resolve(strict=False)
    if path.resolve(strict=False) != canonical_path:
        raise FoundryApplyError("apply log path is fixed at HERMES_HOME/foundry/reviews/apply_log.jsonl")
    if path.exists() and path.is_symlink():
        raise FoundryApplyError("apply log must not be a symlink")
    return path


def _assert_review_log_parseable(review_log_path: str | Path | None = None) -> None:
    path = Path(review_log_path) if review_log_path is not None else default_review_log_path()
    path = path.expanduser()
    if not path.exists():
        return
    if path.is_symlink():
        raise FoundryApplyError("review log must not be a symlink")
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise FoundryApplyError(f"malformed review log at line {line_number}") from exc
            if not isinstance(event, dict):
                raise FoundryApplyError(f"malformed review log event at line {line_number}")


def _load_apply_events(apply_log_path: str | Path | None = None) -> list[dict[str, Any]]:
    path = _normalize_apply_log_path(apply_log_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise FoundryApplyError(f"malformed apply log at line {line_number}") from exc
            if not isinstance(event, dict):
                raise FoundryApplyError(f"malformed apply log event at line {line_number}")
            events.append(event)
    return events


def _already_applied(*, key: str, candidate_sha256: str, apply_log_path: str | Path | None = None) -> bool:
    for event in _load_apply_events(apply_log_path):
        if (
            event.get("result") == "success"
            and event.get("key") == key
            and event.get("candidate_sha256") == candidate_sha256
        ):
            return True
    return False


def _require_approved_candidate(
    key: str,
    *,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_review_log_parseable(review_log_path)
    try:
        record = get_candidate(
            key,
            runs_root=runs_root,
            candidates_root=candidates_root,
            review_log_path=review_log_path,
        )
    except FoundryReviewError as exc:
        raise FoundryApplyError(str(exc)) from exc
    candidate = record.get("candidate")
    if not isinstance(candidate, Mapping):
        raise FoundryApplyError("candidate payload is missing")
    try:
        validate_candidate(candidate)
    except CandidateWriteError as exc:
        raise FoundryApplyError(str(exc)) from exc

    latest_review = record.get("latest_review")
    if not isinstance(latest_review, Mapping):
        raise FoundryApplyError("candidate has not been approved for Phase 5 manual application")
    if latest_review.get("decision") != "approved":
        raise FoundryApplyError("latest review decision is not approved")

    approved_sha = str(latest_review.get("candidate_sha256") or "")
    if not approved_sha:
        raise FoundryApplyError("approval is not content-bound; re-approve candidate before Phase 5 apply")
    try:
        fingerprint = candidate_file_fingerprint(str(record["path"]))
    except FoundryReviewError as exc:
        raise FoundryApplyError(str(exc)) from exc
    if fingerprint["candidate_sha256"] != approved_sha:
        raise FoundryApplyError("candidate bytes changed after approval; re-review before applying")
    approved_size = latest_review.get("candidate_size")
    if approved_size is not None:
        try:
            approved_size_int = int(approved_size)
        except (TypeError, ValueError) as exc:
            raise FoundryApplyError("approval candidate_size is invalid; re-approve candidate") from exc
        if approved_size_int != int(fingerprint["candidate_size"]):
            raise FoundryApplyError("candidate size changed after approval; re-review before applying")
    return record, fingerprint


def _application_paths(
    *,
    key: str,
    candidate_sha256: str,
    applications_root: str | Path | None = None,
    apply_log_path: str | Path | None = None,
) -> dict[str, Path]:
    root = _normalize_applications_root(applications_root)
    key_dir = root / _application_segment(key)
    application_dir = key_dir / candidate_sha256
    paths = {
        "applications_root": root,
        "key_dir": key_dir,
        "application_dir": application_dir,
        "candidate_copy": application_dir / "candidate.json",
        "manual_prompt": application_dir / "manual_prompt.md",
        "manifest": application_dir / "manifest.json",
        "apply_log": _normalize_apply_log_path(apply_log_path),
    }
    canonical_applications_root = default_applications_root().resolve(strict=False)
    for name, path in paths.items():
        if name == "apply_log":
            continue
        _ensure_inside(
            canonical_applications_root,
            path,
            message="application path escapes HERMES_HOME/foundry/applications",
        )
    return paths


def _render_manual_prompt(record: Mapping[str, Any], fingerprint: Mapping[str, Any], plan_sha256: str) -> str:
    candidate = record["candidate"]
    candidate_json = json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "# Clarence Foundry Phase 5 manual application bundle\n\n"
        "This is a local receipt/export bundle, not automatic execution. Do not create cron jobs, "
        "write memory, write skills, edit config, touch the vault, push git, comment on GitHub, "
        "or deliver publicly from this bundle unless James gives a separate explicit approval.\n\n"
        f"- Candidate key: `{record['key']}`\n"
        f"- Candidate path: `{record['path']}`\n"
        f"- Candidate SHA256: `{fingerprint['candidate_sha256']}`\n"
        f"- Candidate bytes: `{fingerprint['candidate_size']}`\n"
        f"- Plan SHA256: `{plan_sha256}`\n"
        "- Phase 5 action: local Foundry application bundle only\n"
        "- Durable writes performed: false\n"
        "- Public delivery performed: false\n\n"
        "## Blocked actions\n"
        + "".join(f"- `{action}`\n" for action in BLOCKED_ACTIONS)
        + "\n## Candidate JSON\n\n"
        f"```json\n{candidate_json}\n```\n"
    )


def build_apply_plan(
    key: str,
    *,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
    applications_root: str | Path | None = None,
    apply_log_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a Phase 5 manual apply plan. This writes nothing."""

    record, fingerprint = _require_approved_candidate(
        key,
        runs_root=runs_root,
        candidates_root=candidates_root,
        review_log_path=review_log_path,
    )
    paths = _application_paths(
        key=key,
        candidate_sha256=fingerprint["candidate_sha256"],
        applications_root=applications_root,
        apply_log_path=apply_log_path,
    )
    writes = [
        {"kind": "candidate_copy", "path": str(paths["candidate_copy"]), "mode": "create"},
        {"kind": "manual_prompt", "path": str(paths["manual_prompt"]), "mode": "create"},
        {"kind": "manifest", "path": str(paths["manifest"]), "mode": "create"},
        {"kind": "apply_log", "path": str(paths["apply_log"]), "mode": "append"},
    ]
    core = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "key": key,
        "candidate_path": str(record["path"]),
        "candidate_sha256": fingerprint["candidate_sha256"],
        "candidate_size": fingerprint["candidate_size"],
        "kind": record["kind"],
        "candidate_id": record["candidate_id"],
        "title": record["title"],
        "latest_review": dict(record["latest_review"]),
        "action": "local_foundry_application_bundle",
        "application_dir": str(paths["application_dir"]),
        "writes": writes,
        "blocked_actions": list(BLOCKED_ACTIONS),
        "requires_manual_confirmation": True,
        "auto_apply": False,
        "durable_writes_performed": False,
        "public_delivery": False,
    }
    plan_sha256 = _sha256_text(_canonical_json(core))
    plan = dict(core)
    plan["plan_sha256"] = plan_sha256
    plan["confirmation_phrase"] = f"APPLY {key} {plan_sha256[:12]}"
    plan["manual_prompt_preview"] = _render_manual_prompt(record, fingerprint, plan_sha256)
    return plan


def _write_new_text(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        raise FoundryApplyError(f"refusing to overwrite existing application artifact: {path}")
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)


def _write_new_bytes(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FoundryApplyError(f"refusing to overwrite existing application artifact: {path}")
    with path.open("xb") as handle:
        handle.write(content)


def _append_apply_log(path: Path, event: Mapping[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise FoundryApplyError("apply log must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise FoundryApplyError("apply log directory must not be a symlink")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")


def apply_candidate(
    key: str,
    *,
    confirm: str,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
    applications_root: str | Path | None = None,
    apply_log_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a local Phase 5 application bundle after exact manual confirmation."""

    plan = build_apply_plan(
        key,
        runs_root=runs_root,
        candidates_root=candidates_root,
        review_log_path=review_log_path,
        applications_root=applications_root,
        apply_log_path=apply_log_path,
    )
    if str(confirm or "") != plan["confirmation_phrase"]:
        raise FoundryApplyError("exact confirmation phrase required")
    if _already_applied(key=key, candidate_sha256=plan["candidate_sha256"], apply_log_path=apply_log_path):
        raise FoundryApplyError("candidate version has already been applied to a local bundle")

    paths = _application_paths(
        key=key,
        candidate_sha256=plan["candidate_sha256"],
        applications_root=applications_root,
        apply_log_path=apply_log_path,
    )
    candidate_bytes = Path(plan["candidate_path"]).read_bytes()
    if hashlib.sha256(candidate_bytes).hexdigest() != plan["candidate_sha256"]:
        raise FoundryApplyError("candidate changed during apply; aborting")

    root = paths["applications_root"]
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise FoundryApplyError("application root must not be a symlink")
    key_dir = paths["key_dir"]
    if key_dir.exists() and key_dir.is_symlink():
        raise FoundryApplyError("application key directory must not be a symlink")
    application_dir = paths["application_dir"]
    if application_dir.exists() or application_dir.is_symlink():
        raise FoundryApplyError("application bundle already exists")
    application_dir.mkdir(parents=True, exist_ok=False)

    manual_prompt = plan.pop("manual_prompt_preview")
    event = {
        "schema_version": SCHEMA_VERSION,
        "result": "success",
        "applied_at": _utc_now(),
        "key": key,
        "candidate_sha256": plan["candidate_sha256"],
        "candidate_size": plan["candidate_size"],
        "plan_sha256": plan["plan_sha256"],
        "application_dir": str(application_dir),
        "writes": [item["path"] for item in plan["writes"]],
        "confirmation_phrase": plan["confirmation_phrase"],
        "auto_apply": False,
        "durable_writes_performed": False,
        "public_delivery": False,
        "blocked_actions": list(BLOCKED_ACTIONS),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "phase": "foundry-phase5-manual-apply-harness",
        "plan": plan,
        "application": event,
    }

    _write_new_bytes(paths["candidate_copy"], candidate_bytes)
    _write_new_text(paths["manual_prompt"], manual_prompt)
    _write_new_text(paths["manifest"], json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _append_apply_log(paths["apply_log"], event)
    return {"success": True, "plan": plan, "application": event}
