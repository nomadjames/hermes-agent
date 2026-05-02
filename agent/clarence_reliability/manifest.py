from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .schema import Case
from .utils import iter_strings, looks_secret_shaped, sha256_json

_RAW_PAYLOAD_KEYS = {"prompt", "input", "result", "args", "content", "conversation", "trace", "fixtures", "user", "system", "messages"}


@dataclass(frozen=True)
class CaseManifestEntry:
    id: str
    path: str
    sha256: str
    title: str
    mode: str
    tags: tuple[str, ...]
    target_component: str
    target_entrypoint: str | None
    source_paths: tuple[str, ...]
    verifier_names: tuple[str, ...]
    fixture_hashes: Mapping[str, str]
    prompt_sha256: str | None = None
    trace_sha256: str | None = None


@dataclass(frozen=True)
class HarnessManifest:
    manifest_version: int
    harness: str
    cases: tuple[CaseManifestEntry, ...]


def _display_path(case: Case, *, case_root: Path) -> str:
    if case.source_path is None:
        return f"builtin/{case.id}.yaml"
    try:
        return case.source_path.relative_to(case_root).as_posix()
    except ValueError:
        return case.source_path.as_posix()


def build_case_manifest(case: Case, *, case_root: Path) -> CaseManifestEntry:
    input_payload = {
        "system": case.input.system,
        "user": case.input.user,
        "conversation": case.input.conversation,
    }
    fixture_hashes = {}
    for fixture in case.fixtures.files:
        if fixture.content is not None:
            fixture_hashes[fixture.path] = sha256_json({"content": fixture.content})
        elif fixture.sha256 is not None:
            fixture_hashes[fixture.path] = fixture.sha256
    return CaseManifestEntry(
        id=case.id,
        path=_display_path(case, case_root=case_root),
        sha256=case.raw_sha256 or sha256_json({"id": case.id, "title": case.title}),
        title=case.title,
        mode=case.mode,
        tags=case.tags,
        target_component=case.target.component,
        target_entrypoint=case.target.entrypoint,
        source_paths=case.target.source_paths,
        verifier_names=tuple(spec.name for spec in case.checks),
        fixture_hashes=fixture_hashes,
        prompt_sha256=sha256_json(input_payload) if any(input_payload.values()) else None,
        trace_sha256=sha256_json(case.trace.to_metadata()) if case.trace else None,
    )


def build_manifest(cases: list[Case], *, case_root: Path) -> HarnessManifest:
    return HarnessManifest(
        manifest_version=0,
        harness="clarence-reliability",
        cases=tuple(build_case_manifest(case, case_root=case_root) for case in cases),
    )


def _entry_to_dict(entry: CaseManifestEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "path": entry.path,
        "sha256": entry.sha256,
        "title": entry.title,
        "mode": entry.mode,
        "tags": list(entry.tags),
        "target_component": entry.target_component,
        "target_entrypoint": entry.target_entrypoint,
        "source_paths": list(entry.source_paths),
        "verifier_names": list(entry.verifier_names),
        "fixture_hashes": dict(entry.fixture_hashes),
        "prompt_sha256": entry.prompt_sha256,
        "trace_sha256": entry.trace_sha256,
    }


def manifest_to_dict(manifest: HarnessManifest) -> dict[str, Any]:
    return {
        "manifest_version": manifest.manifest_version,
        "harness": manifest.harness,
        "cases": [_entry_to_dict(entry) for entry in manifest.cases],
    }


def write_manifest(manifest: HarnessManifest, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest_to_dict(manifest), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _scan_metadata(value: Any, *, path: str = "$", errors: list[str] | None = None) -> list[str]:
    errors = [] if errors is None else errors
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            child_path = f"{path}.{key}"
            if lowered in _RAW_PAYLOAD_KEYS:
                errors.append(f"raw payload key not allowed in manifest: {child_path}")
            _scan_metadata(nested, path=child_path, errors=errors)
    elif isinstance(value, list):
        for idx, nested in enumerate(value):
            _scan_metadata(nested, path=f"{path}[{idx}]", errors=errors)
    elif isinstance(value, str) and looks_secret_shaped(value):
        errors.append(f"secret-shaped value not allowed in manifest: {path}")
    return errors


def assert_metadata_only(manifest_dict: dict[str, Any]) -> list[str]:
    return _scan_metadata(manifest_dict)
