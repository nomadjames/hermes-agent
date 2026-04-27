from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, TypeAlias

Json: TypeAlias = str | int | float | bool | None | list["Json"] | dict[str, "Json"]
CaseMode = Literal["static", "trace", "mock"]
Severity = Literal["error", "warn"]


@dataclass(frozen=True)
class Target:
    component: str
    entrypoint: str | None = None
    source_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseInput:
    system: str | None = None
    user: str | None = None
    conversation: tuple[dict[str, Json], ...] = ()


@dataclass(frozen=True)
class FixtureFile:
    path: str
    content: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class Fixtures:
    env: Mapping[str, str] = field(default_factory=dict)
    files: tuple[FixtureFile, ...] = ()
    now: str | None = None
    memory: tuple[dict[str, Json], ...] = ()
    config: Mapping[str, Json] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifierSpec:
    name: str
    severity: Severity = "error"
    params: Mapping[str, Json] = field(default_factory=dict)


@dataclass(frozen=True)
class Expected:
    final_contains: tuple[str, ...] = ()
    final_not_contains: tuple[str, ...] = ()
    final_regex: str | None = None
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class Case:
    schema_version: int
    id: str
    title: str
    mode: CaseMode
    target: Target
    checks: tuple[VerifierSpec, ...]
    description: str | None = None
    tags: tuple[str, ...] = ()
    risk: str | None = None
    input: CaseInput = field(default_factory=CaseInput)
    fixtures: Fixtures = field(default_factory=Fixtures)
    expected: Expected = field(default_factory=Expected)
    trace: Any = None
    source_path: Path | None = None
    raw_sha256: str | None = None
