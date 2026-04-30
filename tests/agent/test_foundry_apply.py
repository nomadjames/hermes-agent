import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.clarence_foundry.candidates import build_candidate_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "clarence_foundry_apply.py"
KEY = "run:run-one:self_audit:self-audit"


def import_apply():
    return importlib.import_module("agent.clarence_foundry.apply")


def import_review():
    return importlib.import_module("agent.clarence_foundry.review")


def _candidate_payload(*, summary: str = "A candidate that must stay proposal-only.") -> dict:
    return build_candidate_envelope(
        kind="self_audit",
        title="Apply test candidate",
        summary=summary,
        source={"script": "unit-test", "phase": "foundry-phase5-test"},
        payload={"recommendation": "create a local receipt only", "network_calls": "none"},
        slug="self-audit",
    )


def _write_candidate(home: Path, *, summary: str = "A candidate that must stay proposal-only.") -> Path:
    path = home / "foundry" / "runs" / "run-one" / "candidates" / "self_audit" / "self-audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_candidate_payload(summary=summary), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _approve(home: Path):
    _write_candidate(home)
    review = import_review()
    return review.record_review(KEY, decision="approved", reviewer="James", note="Ready for Phase 5 bundle.")


def _reject(home: Path):
    _write_candidate(home)
    review = import_review()
    return review.record_review(KEY, decision="rejected", reviewer="James", note="Not this one.")


def test_preview_requires_approved_candidate_and_writes_nothing(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)
    apply = import_apply()

    plan = apply.build_apply_plan(KEY)

    assert plan["key"] == KEY
    assert plan["action"] == "local_foundry_application_bundle"
    assert plan["requires_manual_confirmation"] is True
    assert plan["auto_apply"] is False
    assert plan["durable_writes_performed"] is False
    assert plan["public_delivery"] is False
    assert "memory_write" in plan["blocked_actions"]
    assert "cron_create" in plan["blocked_actions"]
    assert plan["confirmation_phrase"] == f"APPLY {KEY} {plan['plan_sha256'][:12]}"
    assert not (home / "foundry" / "applications").exists()
    assert not (home / "foundry" / "reviews" / "apply_log.jsonl").exists()
    assert not (home / "cron").exists()


def test_apply_rejects_unreviewed_candidate(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_candidate(home)
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="not been approved"):
        apply.build_apply_plan(KEY)


def test_apply_rejects_rejected_candidate(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _reject(home)
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="not approved"):
        apply.build_apply_plan(KEY)


def test_apply_rejects_approval_without_candidate_hash(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_candidate(home)
    review_log = home / "foundry" / "reviews" / "review_log.jsonl"
    review_log.parent.mkdir(parents=True, exist_ok=True)
    review_log.write_text(
        json.dumps({"key": KEY, "decision": "approved", "reviewer": "James"}) + "\n",
        encoding="utf-8",
    )
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="not content-bound"):
        apply.build_apply_plan(KEY)


def test_apply_rejects_candidate_mutated_after_approval(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)
    _write_candidate(home, summary="Mutated after review.")
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="changed after approval"):
        apply.build_apply_plan(KEY)


def test_apply_requires_exact_confirmation_phrase(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="exact confirmation"):
        apply.apply_candidate(KEY, confirm="yes")

    assert not (home / "foundry" / "applications").exists()
    assert not (home / "foundry" / "reviews" / "apply_log.jsonl").exists()


def test_apply_writes_only_local_bundle_and_apply_log(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    candidate_path = _write_candidate(home)
    review = import_review()
    event = review.record_review(KEY, decision="approved", reviewer="James", note="Ready.")
    apply = import_apply()
    plan = apply.build_apply_plan(KEY)

    result = apply.apply_candidate(KEY, confirm=plan["confirmation_phrase"])

    application = result["application"]
    app_dir = Path(application["application_dir"])
    assert app_dir.exists()
    copied_candidate = app_dir / "candidate.json"
    manual_prompt = app_dir / "manual_prompt.md"
    manifest = app_dir / "manifest.json"
    assert copied_candidate.read_bytes() == candidate_path.read_bytes()
    assert "manual application bundle" in manual_prompt.read_text(encoding="utf-8")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["application"]["durable_writes_performed"] is False
    assert manifest_data["application"]["public_delivery"] is False
    assert manifest_data["plan"]["latest_review"]["candidate_sha256"] == event["candidate_sha256"]
    log_lines = (home / "foundry" / "reviews" / "apply_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    logged = json.loads(log_lines[0])
    assert logged["result"] == "success"
    assert logged["key"] == KEY
    assert logged["candidate_sha256"] == event["candidate_sha256"]
    assert not (home / "memory").exists()
    assert not (home / "skills").exists()
    assert not (home / "config.yaml").exists()
    assert not (home / "cron").exists()
    assert not (home / "vault").exists()


def test_apply_rejects_duplicate_application(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)
    apply = import_apply()
    plan = apply.build_apply_plan(KEY)
    apply.apply_candidate(KEY, confirm=plan["confirmation_phrase"])

    with pytest.raises(apply.FoundryApplyError, match="already"):
        apply.apply_candidate(KEY, confirm=plan["confirmation_phrase"])


def test_apply_rejects_application_root_outside_applications_boundary(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="foundry/applications"):
        apply.build_apply_plan(KEY, applications_root=home / "foundry" / "reviews")


def test_apply_rejects_custom_apply_log_path(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    candidate_path = _write_candidate(home)
    review = import_review()
    review.record_review(KEY, decision="approved", reviewer="James", note="Ready.")
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="apply log path is fixed"):
        apply.build_apply_plan(KEY, apply_log_path=candidate_path)


def test_apply_fails_closed_on_malformed_review_log(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)
    review_log = home / "foundry" / "reviews" / "review_log.jsonl"
    with review_log.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")
    apply = import_apply()

    with pytest.raises(apply.FoundryApplyError, match="malformed review log"):
        apply.build_apply_plan(KEY)


def test_cli_help_preview_and_confirm_gate(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _approve(home)

    help_result = subprocess.run([sys.executable, str(SCRIPT_PATH), "--help"], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    assert help_result.returncode == 0
    assert "manual apply harness" in help_result.stdout.lower()
    assert "--review-log" not in help_result.stdout
    assert "--applications-root" not in help_result.stdout
    assert "--apply-log" not in help_result.stdout

    preview_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "preview", KEY, "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert preview_result.returncode == 0, preview_result.stderr
    plan = json.loads(preview_result.stdout)["plan"]
    assert plan["confirmation_phrase"].startswith(f"APPLY {KEY} ")
    assert not (home / "foundry" / "applications").exists()

    bad_apply = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "apply", KEY, "--confirm", "yes"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bad_apply.returncode == 2
    assert "exact confirmation" in bad_apply.stderr
    assert not (home / "foundry" / "applications").exists()
