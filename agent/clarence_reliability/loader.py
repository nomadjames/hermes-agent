from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

from .schema import Case, CaseInput, Expected, FixtureFile, Fixtures, Target, VerifierSpec
from .trace import Trace
from .utils import canonical_json, sha256_text

_ALLOWED_TOP_LEVEL = {
    "schema_version",
    "id",
    "title",
    "description",
    "mode",
    "tags",
    "risk",
    "target",
    "input",
    "fixtures",
    "expected",
    "trace",
    "checks",
}
_ALLOWED_MODES = {"static", "trace", "mock"}
_ALLOWED_SEVERITIES = {"error", "warn"}
_MAX_CASE_BYTES = 128 * 1024


def _ensure_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _ensure_string_tuple(value: Any, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError(f"{label} must be a list of strings")
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of strings")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{label} entries must be non-empty strings")
        result.append(item)
    return tuple(result)


def _validate_relative_path(path: str, *, label: str) -> None:
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"{label} path must be repo-relative and cannot contain '..': {path}")


def validate_case_dict(data: Mapping[str, Any], *, path: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, Mapping):
        return ["case root must be a mapping"]
    unknown = sorted(key for key in data if key not in _ALLOWED_TOP_LEVEL and not str(key).startswith("x_"))
    if unknown:
        errors.append(f"unknown top-level fields: {', '.join(unknown)}")
    for required in ("schema_version", "id", "title", "mode", "target", "checks"):
        if required not in data:
            errors.append(f"missing required field: {required}")
    if data.get("schema_version") != 0:
        errors.append("schema_version must be 0")
    if data.get("mode") not in _ALLOWED_MODES:
        errors.append("mode must be one of static, trace, mock")
    if not isinstance(data.get("id"), str) or not data.get("id"):
        errors.append("id must be a non-empty string")
    if not isinstance(data.get("title"), str) or not data.get("title"):
        errors.append("title must be a non-empty string")
    target = data.get("target")
    if not isinstance(target, Mapping):
        errors.append("target must be a mapping")
    else:
        if not isinstance(target.get("component"), str) or not target.get("component"):
            errors.append("target.component must be a non-empty string")
        try:
            for source_path in _ensure_string_tuple(target.get("source_paths", []), label="target.source_paths"):
                _validate_relative_path(source_path, label="target.source_paths")
        except ValueError as exc:
            errors.append(str(exc))
    checks = data.get("checks")
    check_names: set[str] = set()
    if not isinstance(checks, list) or not checks:
        errors.append("checks must be a non-empty list")
    else:
        known_verifiers: set[str] | None = None
        try:
            from .verifiers import names as verifier_names

            known_verifiers = set(verifier_names())
        except Exception:
            known_verifiers = None
        for idx, check in enumerate(checks):
            if not isinstance(check, Mapping):
                errors.append(f"checks[{idx}] must be a mapping")
                continue
            check_name = check.get("name")
            if not isinstance(check_name, str) or not check_name:
                errors.append(f"checks[{idx}].name must be a non-empty string")
            else:
                check_names.add(check_name)
                if known_verifiers is not None and check_name not in known_verifiers:
                    errors.append(f"unknown verifier: {check_name}")
            severity = check.get("severity", "error")
            if severity not in _ALLOWED_SEVERITIES:
                errors.append(f"checks[{idx}].severity must be error or warn")
            params = check.get("params", {})
            if params is not None and not isinstance(params, Mapping):
                errors.append(f"checks[{idx}].params must be a mapping")
    expected = data.get("expected") or {}
    if isinstance(expected, Mapping):
        if expected.get("allowed_tools") and "allowed_tool_calls_only" not in check_names:
            errors.append("expected.allowed_tools requires allowed_tool_calls_only verifier")
        if expected.get("denied_tools") and "denied_tool_calls_absent" not in check_names:
            errors.append("expected.denied_tools requires denied_tool_calls_absent verifier")
    try:
        fixtures = _ensure_mapping(data.get("fixtures", {}), label="fixtures")
        for fixture_file in fixtures.get("files", []) or []:
            if not isinstance(fixture_file, Mapping):
                errors.append("fixtures.files entries must be mappings")
                continue
            fixture_path = fixture_file.get("path")
            if not isinstance(fixture_path, str):
                errors.append("fixtures.files path must be a string")
            else:
                _validate_relative_path(fixture_path, label="fixtures.files")
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def load_case_data(data: Mapping[str, Any], *, source_path: Path | None = None, raw_text: str | None = None) -> Case:
    errors = validate_case_dict(data, path=source_path)
    if errors:
        raise ValueError("; ".join(errors))

    target_data = _ensure_mapping(data.get("target"), label="target")
    input_data = _ensure_mapping(data.get("input", {}), label="input")
    fixtures_data = _ensure_mapping(data.get("fixtures", {}), label="fixtures")
    expected_data = _ensure_mapping(data.get("expected", {}), label="expected")

    fixture_files = tuple(
        FixtureFile(path=str(item["path"]), content=item.get("content"), sha256=item.get("sha256"))
        for item in fixtures_data.get("files", []) or []
    )
    checks = tuple(
        VerifierSpec(
            name=str(item["name"]),
            severity=item.get("severity", "error"),
            params=dict(item.get("params") or {}),
        )
        for item in data["checks"]
    )
    trace = Trace.from_mapping(data.get("trace"))
    raw_sha = sha256_text(raw_text) if raw_text is not None else sha256_text(canonical_json(data))
    return Case(
        schema_version=0,
        id=str(data["id"]),
        title=str(data["title"]),
        description=data.get("description"),
        mode=data["mode"],
        tags=_ensure_string_tuple(data.get("tags", []), label="tags"),
        risk=data.get("risk"),
        target=Target(
            component=str(target_data["component"]),
            entrypoint=target_data.get("entrypoint"),
            source_paths=_ensure_string_tuple(target_data.get("source_paths", []), label="target.source_paths"),
        ),
        input=CaseInput(
            system=input_data.get("system"),
            user=input_data.get("user"),
            conversation=tuple(input_data.get("conversation", []) or []),
        ),
        fixtures=Fixtures(
            env=dict(fixtures_data.get("env", {}) or {}),
            files=fixture_files,
            now=fixtures_data.get("now"),
            memory=tuple(fixtures_data.get("memory", []) or []),
            config=dict(fixtures_data.get("config", {}) or {}),
        ),
        expected=Expected(
            final_contains=_ensure_string_tuple(expected_data.get("final_contains", []), label="expected.final_contains"),
            final_not_contains=_ensure_string_tuple(expected_data.get("final_not_contains", []), label="expected.final_not_contains"),
            final_regex=expected_data.get("final_regex"),
            allowed_tools=_ensure_string_tuple(expected_data.get("allowed_tools", []), label="expected.allowed_tools"),
            denied_tools=_ensure_string_tuple(expected_data.get("denied_tools", []), label="expected.denied_tools"),
        ),
        checks=checks,
        trace=trace,
        source_path=source_path,
        raw_sha256=raw_sha,
    )


def load_case_yaml(text: str, *, source_path: Path | None = None) -> Case:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"unsafe or invalid YAML: {source_path or '<memory>'}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("case root must be a mapping")
    return load_case_data(data, source_path=source_path, raw_text=text)


def load_case_file(path: str | Path) -> Case:
    path = Path(path)
    if path.stat().st_size > _MAX_CASE_BYTES:
        raise ValueError(f"case file is too large: {path}")
    text = path.read_text(encoding="utf-8")
    return load_case_yaml(text, source_path=path)


def discover_case_paths(root: str | Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*.yml")) + sorted(path for path in root.rglob("*.yaml"))


def load_cases(paths: Iterable[str | Path]) -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for path in paths:
        case = load_case_file(path)
        if case.id in seen:
            raise ValueError(f"duplicate case id: {case.id}")
        seen.add(case.id)
        cases.append(case)
    return cases
