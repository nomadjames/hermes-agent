from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from .candidates import CandidateWriteError, validate_candidate

SCHEMA_VERSION = 0
_ALLOWED_DECISIONS = frozenset({"approved", "rejected"})
_KEY_RE = re.compile(r"^(run|candidate):[a-z0-9._-]{1,97}:[a-z_]{1,64}:[a-z0-9._-]{1,97}$")
_REVIEWER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,119}$")


class FoundryReviewError(ValueError):
    """Raised when a Foundry review action would violate Phase 4 policy."""


@dataclass(frozen=True)
class CandidateRecord:
    key: str
    path: Path
    origin: str
    run_id: str | None
    kind: str
    candidate_id: str
    title: str
    summary: str
    valid: bool
    error: str | None
    latest_review: dict[str, Any] | None
    candidate: Mapping[str, Any] | None = None

    def to_dict(self, *, include_candidate: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "key": self.key,
            "path": str(self.path),
            "origin": self.origin,
            "run_id": self.run_id,
            "kind": self.kind,
            "candidate_id": self.candidate_id,
            "title": self.title,
            "summary": self.summary,
            "valid": self.valid,
            "error": self.error,
            "latest_review": self.latest_review,
            "review_required": True,
            "auto_apply": False,
            "durable_writes_allowed": False,
        }
        if include_candidate and self.candidate is not None:
            data["candidate"] = self.candidate
        return data


def default_runs_root() -> Path:
    return get_hermes_home() / "foundry" / "runs"


def default_candidates_root() -> Path:
    return get_hermes_home() / "foundry" / "candidates"


def default_reviews_dir() -> Path:
    return get_hermes_home() / "foundry" / "reviews"


def default_review_log_path() -> Path:
    return default_reviews_dir() / "review_log.jsonl"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_json_load(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FoundryReviewError(f"invalid candidate JSON: {path}") from exc
    if not isinstance(data, Mapping):
        raise FoundryReviewError(f"candidate file is not a JSON object: {path}")
    return data


def _candidate_key(origin: str, scope_id: str, kind: str, candidate_id: str) -> str:
    key = f"{origin}:{scope_id}:{kind}:{candidate_id}"
    if not _KEY_RE.fullmatch(key):
        raise FoundryReviewError("unsafe candidate review key")
    return key


def _iter_candidate_files(*, runs_root: str | Path | None = None, candidates_root: str | Path | None = None) -> Iterable[tuple[Path, str, str | None]]:
    runs = Path(runs_root) if runs_root is not None else default_runs_root()
    if runs.exists():
        for path in sorted(runs.glob("*/candidates/*/*.json")):
            if path.is_file() and not path.is_symlink():
                yield path, "run", path.relative_to(runs).parts[0]

    candidates = Path(candidates_root) if candidates_root is not None else default_candidates_root()
    if candidates.exists():
        for path in sorted(candidates.glob("*/*.json")):
            if path.is_file() and not path.is_symlink():
                yield path, "candidate", None


def _load_review_log(review_log_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    path = Path(review_log_path) if review_log_path is not None else default_review_log_path()
    if not path.exists():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(event.get("key", ""))
            if _KEY_RE.fullmatch(key):
                latest[key] = event
    return latest


def _record_from_file(path: Path, origin: str, run_id: str | None, latest_reviews: Mapping[str, dict[str, Any]]) -> CandidateRecord:
    try:
        candidate = _safe_json_load(path)
        validate_candidate(candidate)
        kind = str(candidate["kind"])
        candidate_id = str(candidate["candidate_id"])
        title = str(candidate.get("title") or candidate_id)
        summary = str(candidate.get("summary") or "")
        scope = run_id or "global"
        key = _candidate_key(origin, scope, kind, candidate_id)
        return CandidateRecord(
            key=key,
            path=path,
            origin=origin,
            run_id=run_id,
            kind=kind,
            candidate_id=candidate_id,
            title=title,
            summary=summary,
            valid=True,
            error=None,
            latest_review=latest_reviews.get(key),
            candidate=candidate,
        )
    except (CandidateWriteError, FoundryReviewError, OSError, KeyError, TypeError) as exc:
        kind = path.parent.name
        candidate_id = path.stem
        scope = run_id or "global"
        try:
            key = _candidate_key(origin, scope, kind, candidate_id)
        except FoundryReviewError:
            key = f"invalid:{path.name}"
        return CandidateRecord(
            key=key,
            path=path,
            origin=origin,
            run_id=run_id,
            kind=kind,
            candidate_id=candidate_id,
            title=candidate_id,
            summary="",
            valid=False,
            error=str(exc),
            latest_review=latest_reviews.get(key),
            candidate=None,
        )


def list_candidates(
    *,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
    include_reviewed: bool = True,
) -> list[dict[str, Any]]:
    """List local Foundry candidates without applying or delivering them."""

    latest_reviews = _load_review_log(review_log_path)
    records = [
        _record_from_file(path, origin, run_id, latest_reviews)
        for path, origin, run_id in _iter_candidate_files(runs_root=runs_root, candidates_root=candidates_root)
    ]
    if not include_reviewed:
        records = [record for record in records if record.latest_review is None]
    return [record.to_dict() for record in records]


def get_candidate(
    key: str,
    *,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
) -> dict[str, Any]:
    for record in _candidate_records(
        runs_root=runs_root,
        candidates_root=candidates_root,
        review_log_path=review_log_path,
    ):
        if record.key == key:
            return record.to_dict(include_candidate=True)
    raise FoundryReviewError(f"candidate not found: {key}")


def _candidate_records(
    *,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
) -> list[CandidateRecord]:
    latest_reviews = _load_review_log(review_log_path)
    return [
        _record_from_file(path, origin, run_id, latest_reviews)
        for path, origin, run_id in _iter_candidate_files(runs_root=runs_root, candidates_root=candidates_root)
    ]


def _require_record(key: str, records: Iterable[CandidateRecord]) -> CandidateRecord:
    if not _KEY_RE.fullmatch(key):
        raise FoundryReviewError("unsafe candidate review key")
    for record in records:
        if record.key == key:
            if not record.valid or record.candidate is None:
                raise FoundryReviewError(f"candidate is invalid and cannot be reviewed: {record.error}")
            return record
    raise FoundryReviewError(f"candidate not found: {key}")


def record_review(
    key: str,
    *,
    decision: str,
    reviewer: str,
    note: str = "",
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append a local review-log decision. Approval never applies the candidate."""

    normalized_decision = str(decision).strip().lower()
    if normalized_decision not in _ALLOWED_DECISIONS:
        raise FoundryReviewError("decision must be approved or rejected")
    reviewer_text = str(reviewer).strip()
    if not _REVIEWER_RE.fullmatch(reviewer_text):
        raise FoundryReviewError("reviewer must be a short human-readable name")

    record = _require_record(
        key,
        _candidate_records(runs_root=runs_root, candidates_root=candidates_root, review_log_path=review_log_path),
    )
    assert record.candidate is not None
    validate_candidate(record.candidate)

    event = {
        "schema_version": SCHEMA_VERSION,
        "reviewed_at": _utc_now(),
        "key": key,
        "decision": normalized_decision,
        "reviewer": reviewer_text,
        "note": str(note or "")[:2000],
        "candidate_path": str(record.path),
        "candidate_id": record.candidate_id,
        "kind": record.kind,
        "title": record.title,
        "proposal_only": True,
        "review_required": True,
        "auto_apply": False,
        "review_log_write": True,
        "durable_writes_allowed": False,
    }

    log_path = Path(review_log_path) if review_log_path is not None else default_review_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def render_apply_prompt(
    key: str,
    *,
    runs_root: str | Path | None = None,
    candidates_root: str | Path | None = None,
    review_log_path: str | Path | None = None,
) -> str:
    """Render a manual prompt for a normal Hermes session. This writes nothing."""

    record = _require_record(
        key,
        _candidate_records(runs_root=runs_root, candidates_root=candidates_root, review_log_path=review_log_path),
    )
    candidate_json = json.dumps(record.candidate, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "Manual Clarence Foundry candidate review.\n\n"
        "Do not apply this automatically. Do not create cron jobs, write memory, write skills, "
        "edit config, push git, comment on GitHub, or deliver publicly unless James explicitly asks.\n\n"
        f"Candidate key: {record.key}\n"
        f"Candidate path: {record.path}\n\n"
        "Candidate JSON:\n"
        f"```json\n{candidate_json}\n```"
    )


def build_paused_local_cron_manifest(*, workdir: str | Path, schedule: str = "10 2 * * *") -> dict[str, Any]:
    """Return, but do not install, the Phase 4 paused local cron job shape."""

    prompt = (
        "Run local Clarence Foundry review only. In the configured workdir, run "
        "python scripts/clarence_foundry_nightly.py --repo-root . --timeout-seconds 120 --json, "
        "then run python scripts/clarence_foundry_review.py list --json. Summarize locally only. "
        "Do not send public messages. Do not write memory, skills, config, cron, git, vault, or routing policy. "
        "Do not merge PR #1."
    )
    return {
        "name": "Clarence Foundry local nightly review",
        "schedule": schedule,
        "prompt": prompt,
        "deliver": "local",
        "workdir": str(Path(workdir).expanduser().resolve()),
        "enabled_toolsets": ["terminal"],
        "paused": True,
        "reason": "Phase 4 review gate; manual resume only",
        "auto_apply": False,
        "public_delivery": False,
    }
