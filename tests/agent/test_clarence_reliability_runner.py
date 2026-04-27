import json
import socket
import subprocess
import sys
from pathlib import Path

from agent.clarence_reliability.cases import BUILTIN_CASE_IDS, load_builtin_cases
from agent.clarence_reliability.runner import main, run_cases
from agent.clarence_reliability.report import format_run_result

FORBIDDEN_LIVE_MODULES = (
    "run_agent",
    "model_tools",
    "tools.mcp_tool",
    "hermes_cli.plugins",
)


def test_builtin_cases_pass_offline(tmp_path):
    cases = load_builtin_cases()

    result = run_cases(cases, repo_root=tmp_path, case_root=tmp_path)

    assert len(cases) == 5
    assert tuple(case.id for case in cases) == BUILTIN_CASE_IDS
    assert result.ok, format_run_result(result)


def test_offline_runner_does_not_use_network_or_subprocess(monkeypatch, tmp_path):
    def explode(*args, **kwargs):
        raise AssertionError("offline runner attempted live side effect")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    monkeypatch.setattr(socket, "socket", explode)

    result = run_cases(load_builtin_cases(), repo_root=tmp_path, case_root=tmp_path)

    assert result.ok, format_run_result(result)


def test_static_runner_does_not_import_live_agent_stack(tmp_path):
    for name in FORBIDDEN_LIVE_MODULES:
        sys.modules.pop(name, None)

    result = run_cases(load_builtin_cases(), repo_root=tmp_path, case_root=tmp_path)

    assert result.ok, format_run_result(result)
    assert not [name for name in FORBIDDEN_LIVE_MODULES if name in sys.modules]


def test_clean_process_import_does_not_load_live_agent_stack(tmp_path):
    code = """
import json
import sys
from agent.clarence_reliability.cases import load_builtin_cases
from agent.clarence_reliability.runner import run_cases
forbidden = ('run_agent', 'model_tools', 'tools.mcp_tool', 'hermes_cli.plugins')
result = run_cases(load_builtin_cases(), repo_root='.', case_root='.')
print(json.dumps({'ok': result.ok, 'forbidden': [name for name in forbidden if name in sys.modules]}))
"""

    repo_root = Path(__file__).parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    assert payload == {"ok": True, "forbidden": []}


def test_main_defaults_to_builtin_cases_when_no_case_paths(capsys):
    exit_code = main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert [case["case_id"] for case in payload["cases"]] == list(BUILTIN_CASE_IDS)


def test_main_returns_error_when_supplied_path_has_no_cases(tmp_path, capsys):
    empty_case_dir = tmp_path / "empty"
    empty_case_dir.mkdir()

    exit_code = main([str(empty_case_dir), "--json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "No case YAML files found" in captured.err
    assert captured.out == ""


def test_module_execution_has_no_runpy_warning():
    repo_root = Path(__file__).parents[2]

    completed = subprocess.run(
        [sys.executable, "-m", "agent.clarence_reliability.runner", "--json"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert "RuntimeWarning" not in completed.stderr
