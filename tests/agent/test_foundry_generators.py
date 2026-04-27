import importlib.util
import json
from pathlib import Path

import pytest

from agent.clarence_foundry.candidates import validate_candidate

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATHS = [
    REPO_ROOT / "scripts" / "foundry_self_audit.py",
    REPO_ROOT / "scripts" / "foundry_skill_candidates.py",
    REPO_ROOT / "scripts" / "foundry_routing_bench.py",
]


def load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def json_files(root: Path):
    return sorted(root.rglob("*.json"))


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_importing_generator_script_does_not_write(tmp_path, monkeypatch, script_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))

    load_script(script_path)

    assert not (tmp_path / "hermes-home" / "foundry").exists()


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_build_candidate_returns_valid_report_only_candidate(tmp_path, script_path):
    module = load_script(script_path)

    candidate = module.build_candidate(repo_root=REPO_ROOT)

    validate_candidate(candidate)
    assert candidate["proposal_only"] is True
    assert candidate["review_required"] is True
    assert candidate["durable_writes_allowed"] is False
    assert candidate["source"]["script"] == f"scripts/{script_path.name}"


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_generator_cli_writes_only_candidate_under_out_dir(tmp_path, monkeypatch, script_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    module = load_script(script_path)
    out_dir = tmp_path / "candidate-root"

    code = module.main([
        "--repo-root",
        str(REPO_ROOT),
        "--out-dir",
        str(out_dir),
        "--slug",
        "unit-test",
    ])

    assert code == 0
    files = json_files(out_dir)
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    validate_candidate(data)
    assert data["proposal_only"] is True
    assert not (tmp_path / "hermes-home" / "memories").exists()
    assert not (tmp_path / "hermes-home" / "skills").exists()
    assert not (tmp_path / "hermes-home" / "config.yaml").exists()


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_print_json_validates_but_writes_nothing(tmp_path, capsys, script_path):
    module = load_script(script_path)
    out_dir = tmp_path / "candidate-root"

    code = module.main([
        "--repo-root",
        str(REPO_ROOT),
        "--out-dir",
        str(out_dir),
        "--slug",
        "print-only",
        "--print-json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    validate_candidate(data)
    assert not out_dir.exists()


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_generator_collision_fails_closed_unless_overwrite(tmp_path, script_path):
    module = load_script(script_path)
    out_dir = tmp_path / "candidate-root"
    args = ["--repo-root", str(REPO_ROOT), "--out-dir", str(out_dir), "--slug", "collision"]

    assert module.main(args) == 0
    assert module.main(args) == 2
    assert module.main(args + ["--overwrite"]) == 0
