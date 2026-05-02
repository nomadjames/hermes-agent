import builtins
from pathlib import Path

import pytest

from agent.clarence_reliability.loader import load_case_data, load_case_file, load_cases


def minimal_case(**overrides):
    data = {
        "schema_version": 0,
        "id": "loader.valid_case",
        "title": "Valid case",
        "mode": "trace",
        "target": {"component": "clarence", "source_paths": ["run_agent.py"]},
        "input": {"user": "What model are you running?"},
        "trace": {"events": [{"type": "assistant_message", "name": "final", "result": "I checked config."}]},
        "checks": [{"name": "final_contains", "params": {"text": "checked"}}],
    }
    data.update(overrides)
    return data


def test_load_case_data_accepts_minimal_valid_case():
    case = load_case_data(minimal_case(), source_path=Path("case.yaml"))

    assert case.id == "loader.valid_case"
    assert case.mode == "trace"
    assert case.target.source_paths == ("run_agent.py",)
    assert case.checks[0].name == "final_contains"
    assert case.trace.final_message() == "I checked config."


def test_load_case_data_rejects_unknown_top_level_fields():
    data = minimal_case(misspelled_safety_field=True)

    with pytest.raises(ValueError, match="unknown top-level fields"):
        load_case_data(data)


def test_load_case_data_rejects_duplicate_case_ids(tmp_path):
    case_a = tmp_path / "a.yaml"
    case_b = tmp_path / "b.yaml"
    payload = """
schema_version: 0
id: duplicate.case
title: Duplicate
mode: trace
target:
  component: clarence
checks:
  - name: offline_only
"""
    case_a.write_text(payload, encoding="utf-8")
    case_b.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate case id"):
        load_cases([case_a, case_b])


def test_load_case_file_uses_safe_yaml_loader(tmp_path):
    malicious = tmp_path / "malicious.yaml"
    malicious.write_text("!!python/object/apply:os.system ['touch SHOULD_NOT_EXIST']", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe or invalid YAML"):
        load_case_file(malicious)

    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


def test_load_case_data_rejects_absolute_or_parent_paths():
    data = minimal_case(target={"component": "clarence", "source_paths": ["/etc/passwd", "../secrets"]})

    with pytest.raises(ValueError, match="must be repo-relative"):
        load_case_data(data)


def test_load_case_data_rejects_unknown_verifier_names():
    data = minimal_case(checks=[{"name": "definitely_not_a_real_verifier"}])

    with pytest.raises(ValueError, match="unknown verifier"):
        load_case_data(data)


def test_load_case_data_fails_closed_when_verifier_registry_import_fails(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "verifiers" and level == 1 and fromlist == ("names",):
            raise ImportError("simulated verifier registry import failure")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(ImportError, match="simulated verifier registry import failure"):
        load_case_data(minimal_case())


def test_load_case_data_requires_tool_policy_verifiers_when_expected_tools_declared():
    data = minimal_case(expected={"denied_tools": ["send_message"]}, checks=[{"name": "offline_only"}])

    with pytest.raises(ValueError, match="denied_tool_calls_absent"):
        load_case_data(data)
