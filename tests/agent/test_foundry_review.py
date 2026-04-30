import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.clarence_foundry.candidates import build_candidate_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "clarence_foundry_review.py"


def import_review():
    return importlib.import_module("agent.clarence_foundry.review")


def _write_candidate(root: Path, *, run_id: str = "run-one", kind: str = "self_audit", slug: str = "self-audit") -> Path:
    candidate = build_candidate_envelope(
        kind=kind,
        title="Review test candidate",
        summary="A candidate that must stay proposal-only.",
        source={"script": "unit-test", "phase": "foundry-phase4-test"},
        payload={"recommendation": "keep review local", "network_calls": "none"},
        slug=slug,
    )
    path = root / "foundry" / "runs" / run_id / "candidates" / kind / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate), encoding="utf-8")
    return path


def test_importing_review_does_not_create_foundry(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))

    import_review()

    assert not (tmp_path / "hermes-home" / "foundry").exists()


def test_list_candidates_discovers_run_local_candidate(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    path = _write_candidate(home)
    review = import_review()

    candidates = review.list_candidates()

    assert len(candidates) == 1
    item = candidates[0]
    assert item["key"] == "run:run-one:self_audit:self-audit"
    assert item["path"] == str(path)
    assert item["origin"] == "run"
    assert item["run_id"] == "run-one"
    assert item["valid"] is True
    assert item["review_required"] is True
    assert item["auto_apply"] is False
    assert item["durable_writes_allowed"] is False


def test_approve_records_local_review_without_applying(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_candidate(home)
    review = import_review()

    event = review.record_review(
        "run:run-one:self_audit:self-audit",
        decision="approved",
        reviewer="James",
        note="Looks safe for manual handling.",
    )

    log_path = home / "foundry" / "reviews" / "review_log.jsonl"
    assert event["decision"] == "approved"
    assert event["auto_apply"] is False
    assert event["durable_writes_allowed"] is False
    assert log_path.exists()
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1
    assert not (home / "memories").exists()
    assert not (home / "skills").exists()
    assert not (home / "config.yaml").exists()
    assert not (home / "cron").exists()

    listed = review.list_candidates()
    assert listed[0]["latest_review"]["decision"] == "approved"


def test_reject_keeps_candidate_auditable(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    candidate_path = _write_candidate(home)
    review = import_review()

    review.record_review(
        "run:run-one:self_audit:self-audit",
        decision="rejected",
        reviewer="James",
        note="Not useful.",
    )

    assert candidate_path.exists()
    assert review.list_candidates()[0]["latest_review"]["decision"] == "rejected"


def test_invalid_candidate_cannot_be_approved(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    bad = home / "foundry" / "runs" / "run-one" / "candidates" / "self_audit" / "bad.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(json.dumps({"kind": "self_audit", "candidate_id": "bad"}), encoding="utf-8")
    review = import_review()

    items = review.list_candidates()
    assert len(items) == 1
    assert items[0]["valid"] is False

    with pytest.raises(review.FoundryReviewError):
        review.record_review(items[0]["key"], decision="approved", reviewer="James")

    assert not (home / "foundry" / "reviews" / "review_log.jsonl").exists()


def test_apply_prompt_is_manual_and_writes_nothing(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_candidate(home)
    review = import_review()

    prompt = review.render_apply_prompt("run:run-one:self_audit:self-audit")

    assert "Do not apply this automatically" in prompt
    assert "Candidate JSON" in prompt
    assert not (home / "foundry" / "reviews").exists()
    assert not (home / "cron").exists()


def test_cli_help_and_manifest_do_not_create_artifacts(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))

    help_result = subprocess.run([sys.executable, str(SCRIPT_PATH), "--help"], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    assert help_result.returncode == 0
    assert "local-only" in help_result.stdout.lower()
    assert not (home / "foundry").exists()

    manifest_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "paused-cron-manifest", "--workdir", str(REPO_ROOT), "--schedule", "10 2 * * *"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert manifest_result.returncode == 0, manifest_result.stderr
    manifest = json.loads(manifest_result.stdout)["manifest"]
    assert manifest["paused"] is True
    assert manifest["deliver"] == "local"
    assert manifest["public_delivery"] is False
    assert manifest["auto_apply"] is False
    assert not (home / "foundry").exists()
