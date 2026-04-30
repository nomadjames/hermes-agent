import json
from argparse import Namespace

import pytest


@pytest.fixture()
def tmp_cron_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


def test_create_job_can_be_atomically_paused(tmp_cron_dir):
    from cron.jobs import create_job, get_due_jobs, get_job, list_jobs

    job = create_job(
        prompt="Review local Foundry artifacts only",
        schedule="every 1h",
        deliver="local",
        paused=True,
        paused_reason="manual review gate",
    )

    assert job["enabled"] is False
    assert job["state"] == "paused"
    assert job["paused_at"] is not None
    assert job["paused_reason"] == "manual review gate"
    assert job["next_run_at"] is None
    assert job["deliver"] == "local"
    assert get_job(job["id"])["state"] == "paused"
    assert list_jobs() == []
    assert list_jobs(include_disabled=True)[0]["id"] == job["id"]
    assert get_due_jobs() == []


def test_cronjob_tool_create_paused_local_job(tmp_cron_dir):
    from tools.cronjob_tools import CRONJOB_SCHEMA, cronjob

    result = json.loads(
        cronjob(
            action="create",
            prompt="Review local Foundry artifacts only",
            schedule="every 1h",
            name="Foundry paused review",
            deliver="local",
            paused=True,
            reason="Phase 4 gate",
        )
    )

    assert result["success"] is True
    assert result["state"] == "paused"
    assert result["enabled"] is False
    assert result["next_run_at"] is None
    assert result["job"]["deliver"] == "local"
    assert result["job"]["state"] == "paused"
    assert result["job"]["paused_reason"] == "Phase 4 gate"
    assert "paused" in CRONJOB_SCHEMA["parameters"]["properties"]

    active = json.loads(cronjob(action="list", include_disabled=False))
    assert active["count"] == 0
    all_jobs = json.loads(cronjob(action="list", include_disabled=True))
    assert all_jobs["count"] == 1
    assert all_jobs["jobs"][0]["state"] == "paused"


def test_cli_create_paused_job(tmp_cron_dir, capsys):
    from cron.jobs import get_due_jobs, list_jobs
    from hermes_cli.cron import cron_command

    cron_command(
        Namespace(
            cron_command="create",
            schedule="every 1h",
            prompt="Review local Foundry artifacts only",
            name="Foundry paused review",
            deliver="local",
            repeat=None,
            skill=None,
            skills=None,
            script=None,
            workdir=None,
            paused=True,
            reason="Phase 4 gate",
        )
    )

    out = capsys.readouterr().out
    assert "Created job" in out
    assert "State: paused" in out
    assert "Deliver: local" in out
    assert list_jobs() == []
    all_jobs = list_jobs(include_disabled=True)
    assert len(all_jobs) == 1
    assert all_jobs[0]["state"] == "paused"
    assert all_jobs[0]["next_run_at"] is None
    assert get_due_jobs() == []
