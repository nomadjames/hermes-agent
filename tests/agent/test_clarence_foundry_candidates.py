import json
from pathlib import Path

import pytest

from agent.clarence_foundry.candidates import (
    CandidateWriteError,
    build_candidate_envelope,
    default_candidates_dir,
    validate_candidate,
    write_candidate,
)


def candidate(kind="self_audit", payload=None, slug="unit-candidate"):
    return build_candidate_envelope(
        kind=kind,
        title="Unit candidate",
        summary="A report-only test candidate.",
        source="tests/agent/test_clarence_foundry_candidates.py",
        payload=payload or {"checks": [{"id": "safe", "status": "manual_review"}]},
        slug=slug,
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_candidates_dir_honors_hermes_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    assert default_candidates_dir() == hermes_home / "foundry" / "candidates"

    result = write_candidate(candidate(slug="default-root"))

    assert result.path.parent == hermes_home / "foundry" / "candidates" / "self_audit"
    assert result.path.exists()


def test_custom_root_writes_candidate_with_required_metadata(tmp_path):
    root = tmp_path / "candidates"
    result = write_candidate(candidate(kind="skill_candidates", slug="metadata-check"), root=root)
    data = read_json(result.path)

    assert result.path == root / "skill_candidates" / "metadata-check.json"
    assert data["schema_version"] == 0
    assert data["proposal_only"] is True
    assert data["review_required"] is True
    assert data["durable_writes_allowed"] is False
    assert data["kind"] == "skill_candidates"
    assert data["source"]["phase"] == "foundry-phase2"


@pytest.mark.parametrize("bad_kind", ["unknown", "../../memories", "memory_write", ""])
def test_rejects_unknown_or_pathlike_kinds(tmp_path, bad_kind):
    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(kind=bad_kind), root=tmp_path / "candidates")


@pytest.mark.parametrize("bad_slug", ["../memory", "/tmp/x", "foo/bar", r"foo\\bar", "~secret", ""])
def test_rejects_path_traversal_or_unsafe_slugs(tmp_path, bad_slug):
    root = tmp_path / "candidates"

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(slug="safe"), root=root, slug=bad_slug)

    assert not (tmp_path / "memory.json").exists()


def test_rejects_symlink_kind_directory_escape(tmp_path):
    root = tmp_path / "candidates"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "self_audit").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(slug="symlink-escape"), root=root)

    assert not (outside / "symlink-escape.json").exists()


def test_rejects_existing_candidate_without_overwrite(tmp_path):
    root = tmp_path / "candidates"
    first = write_candidate(candidate(slug="collision"), root=root)

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(slug="collision"), root=root)

    second = write_candidate(candidate(slug="collision"), root=root, overwrite=True)
    assert second.path == first.path


def test_rejects_secret_key_without_echoing_value(tmp_path):
    root = tmp_path / "candidates"
    bad_key = "api" + "_key"
    bad_value = "value-that-must-not-be-echoed"

    with pytest.raises(CandidateWriteError) as excinfo:
        write_candidate(candidate(payload={bad_key: bad_value}), root=root)

    assert bad_value not in str(excinfo.value)
    assert not list(root.rglob("*.json"))


def test_rejects_secret_shaped_value(tmp_path):
    root = tmp_path / "candidates"
    shaped_value = "sk-" + "a" * 32

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(payload={"redacted_example": shaped_value}), root=root)

    assert not list(root.rglob("*.json"))


def test_rejects_raw_private_dump_and_oversized_strings(tmp_path):
    root = tmp_path / "candidates"

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(payload={"raw_dump": "contents from " + ".env"}), root=root)

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(payload={"raw_dump": {"line": "contents from " + ".env"}}), root=root)

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(payload={"raw_dump": [{"line": "contents from " + ".env"}]}), root=root)

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(payload={"raw_dump": {"contents from " + ".env": "safe value"}}), root=root)

    with pytest.raises(CandidateWriteError):
        write_candidate(candidate(payload={"summary": "x" * 13000}), root=root)

    assert not list(root.rglob("*.json"))


def test_rejects_conflicting_safety_metadata():
    safe = candidate()
    unsafe = dict(safe)
    unsafe["proposal_only"] = False

    with pytest.raises(CandidateWriteError):
        validate_candidate(unsafe)


def test_validate_rejects_non_json_serializable_payload():
    unsafe = candidate()
    unsafe["payload"] = {"bad": object()}

    with pytest.raises(CandidateWriteError):
        validate_candidate(unsafe)


def test_importing_candidate_module_does_not_create_foundry_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    __import__("agent.clarence_foundry.candidates")

    assert not (tmp_path / "hermes-home" / "foundry").exists()
