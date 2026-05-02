from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from hermes_constants import get_hermes_home
from utils import atomic_json_write

SCHEMA_VERSION = 0
MAX_SERIALIZED_BYTES = 256 * 1024
MAX_STRING_CHARS = 12_000
ALLOWED_KINDS = frozenset({"self_audit", "skill_candidates", "routing_bench"})
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,96}$")
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "set-cookie",
    "credential",
    "private_key",
    "client_secret",
    "refresh_token",
    "access_token",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bBearer [A-Za-z0-9._~+/=-]{20,}\b"),
    re.compile(r"\b(?:OPENAI|ANTHROPIC|PERPLEXITY)_API_KEY\s*="),
)
_RAW_DUMP_KEY_FRAGMENTS = ("raw", "dump", "full_text", "transcript", "file_contents", "config_contents", "env_contents")
_PRIVATE_PATH_MARKERS = (
    "~/.hermes/.env",
    ".hermes/.env",
    ".env",
    ".netrc",
    ".ssh/",
    "id_rsa",
    "id_ed25519",
    "config.yaml",
    "credentials",
)
_REDACTED_VALUES = {"***", "<redacted>", "redacted", "[redacted]", "<secret>", "[secret]"}


class CandidateWriteError(ValueError):
    """Raised when a Foundry candidate would violate Phase 2 safety policy."""


@dataclass(frozen=True)
class CandidateWriteResult:
    path: Path
    candidate_id: str
    bytes_written: int


def default_candidates_dir() -> Path:
    return get_hermes_home() / "foundry" / "candidates"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")
    if not slug:
        slug = "candidate"
    return slug[:97]


def _validate_kind(kind: str) -> str:
    if kind not in ALLOWED_KINDS:
        raise CandidateWriteError(f"unsupported candidate kind at $.kind: {kind!r}")
    return kind


def _validate_slug(slug: str, *, path: str = "slug") -> str:
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise CandidateWriteError(f"unsafe candidate {path}")
    if any(part in slug for part in ("/", "\\", "..", "~")):
        raise CandidateWriteError(f"unsafe candidate {path}")
    return slug


def build_candidate_envelope(
    *,
    kind: str,
    title: str,
    payload: Mapping[str, Any],
    source: str | Mapping[str, Any],
    summary: str = "",
    slug: str | None = None,
) -> dict[str, Any]:
    kind = _validate_kind(kind)
    candidate_id = _validate_slug(slug, path="candidate_id") if slug else _slugify(f"{kind}-{title}")
    if isinstance(source, str):
        source_payload: dict[str, Any] = {"script": source, "phase": "foundry-phase2"}
    else:
        source_payload = dict(source)
        source_payload.setdefault("phase", "foundry-phase2")
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "candidate_id": candidate_id,
        "title": title,
        "summary": summary,
        "proposal_only": True,
        "review_required": True,
        "durable_writes_allowed": False,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": source_payload,
        "payload": dict(payload),
    }
    validate_candidate(candidate)
    return candidate


def _json_dumps(candidate: Mapping[str, Any]) -> str:
    try:
        return json.dumps(candidate, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise CandidateWriteError("candidate is not JSON-serializable") from exc


def _is_redacted(value: str) -> bool:
    return value.strip().lower() in _REDACTED_VALUES


def _scan_value(
    value: Any,
    *,
    path: str,
    key_context: str | None = None,
    raw_dump_context: bool = False,
) -> None:
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key)
            key_lower = key.lower()
            nested_path = f"{path}.{key}" if path else f"$.{key}"
            if len(key) > MAX_STRING_CHARS:
                raise CandidateWriteError(f"oversized mapping key rejected at {nested_path}")
            if any(fragment in key_lower for fragment in _SECRET_KEY_FRAGMENTS):
                raise CandidateWriteError(f"secret-shaped key rejected at {nested_path}")
            nested_raw_dump_context = raw_dump_context or any(
                fragment in key_lower for fragment in _RAW_DUMP_KEY_FRAGMENTS
            )
            if raw_dump_context and any(marker in key_lower for marker in _PRIVATE_PATH_MARKERS):
                raise CandidateWriteError(f"raw private dump rejected at {nested_path}")
            if not _is_redacted(key) and any(pattern.search(key) for pattern in _SECRET_VALUE_PATTERNS):
                raise CandidateWriteError(f"secret-shaped key rejected at {nested_path}")
            _scan_value(
                nested,
                path=nested_path,
                key_context=key_lower,
                raw_dump_context=nested_raw_dump_context,
            )
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _scan_value(
                nested,
                path=f"{path}[{index}]",
                key_context=key_context,
                raw_dump_context=raw_dump_context,
            )
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        if not isinstance(value, str):
            return
        if len(value) > MAX_STRING_CHARS:
            raise CandidateWriteError(f"oversized string rejected at {path}")
        if _is_redacted(value):
            return
        if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            raise CandidateWriteError(f"secret-shaped value rejected at {path}")
        lower = value.lower()
        if raw_dump_context or (key_context and any(fragment in key_context for fragment in _RAW_DUMP_KEY_FRAGMENTS)):
            if any(marker in lower for marker in _PRIVATE_PATH_MARKERS):
                raise CandidateWriteError(f"raw private dump rejected at {path}")
        return
    raise CandidateWriteError(f"unsupported non-JSON value at {path}")


def validate_candidate(candidate: Mapping[str, Any]) -> None:
    if not isinstance(candidate, Mapping):
        raise CandidateWriteError("candidate must be a mapping")
    required = {
        "schema_version",
        "kind",
        "candidate_id",
        "title",
        "summary",
        "proposal_only",
        "review_required",
        "durable_writes_allowed",
        "created_at",
        "source",
        "payload",
    }
    missing = sorted(required - set(candidate))
    if missing:
        raise CandidateWriteError(f"candidate missing required fields: {', '.join(missing)}")
    if candidate["schema_version"] != SCHEMA_VERSION:
        raise CandidateWriteError("unsupported candidate schema_version")
    _validate_kind(str(candidate["kind"]))
    _validate_slug(str(candidate["candidate_id"]), path="candidate_id")
    if candidate["proposal_only"] is not True:
        raise CandidateWriteError("candidate must be proposal_only")
    if candidate["review_required"] is not True:
        raise CandidateWriteError("candidate must be review_required")
    if candidate["durable_writes_allowed"] is not False:
        raise CandidateWriteError("candidate must forbid durable writes")
    if not isinstance(candidate["source"], Mapping):
        raise CandidateWriteError("candidate source must be a mapping")
    if not isinstance(candidate["payload"], Mapping):
        raise CandidateWriteError("candidate payload must be a mapping")
    serialized = _json_dumps(candidate)
    if len(serialized.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise CandidateWriteError("candidate exceeds Phase 2 size limit")
    _scan_value(candidate, path="$")


def _resolve_root(root: str | Path | None) -> Path:
    candidate_root = Path(root) if root is not None else default_candidates_dir()
    if candidate_root.exists() and not candidate_root.is_dir():
        raise CandidateWriteError("candidate root exists and is not a directory")
    return candidate_root


def _ensure_inside_root(root: Path, target: Path) -> None:
    root_resolved = root.resolve(strict=False)
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise CandidateWriteError("candidate output path escapes candidate root") from exc


def write_candidate(
    candidate: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    slug: str | None = None,
    overwrite: bool = False,
) -> CandidateWriteResult:
    validate_candidate(candidate)
    kind = str(candidate["kind"])
    file_slug = _validate_slug(str(candidate["candidate_id"]) if slug is None else slug, path="slug")
    candidate_root = _resolve_root(root)
    kind_dir = candidate_root / kind
    target = kind_dir / f"{file_slug}.json"
    _ensure_inside_root(candidate_root, kind_dir)
    _ensure_inside_root(candidate_root, target)
    if kind_dir.exists() and kind_dir.is_symlink():
        _ensure_inside_root(candidate_root, kind_dir.resolve(strict=True))
    if target.exists():
        _ensure_inside_root(candidate_root, target)
        if not overwrite:
            raise CandidateWriteError("candidate already exists")
    atomic_json_write(target, candidate, sort_keys=True)
    return CandidateWriteResult(path=target, candidate_id=str(candidate["candidate_id"]), bytes_written=target.stat().st_size)
