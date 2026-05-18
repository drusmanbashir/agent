from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from agent.hpc.cli.hpc_dashboard_web import build_app, run_poll_jobs
from agent.hpc.tools.job_registry import JobRecord, JobRegistry


def write_job(root: Path, job_id: str, state: str, finished_at: str = "-") -> None:
    registry = JobRegistry(root)
    job = JobRecord(
        job_id=job_id,
        submitted_at="2026-05-12T09:30:00",
        sbatch_file="train.sbatch",
        job_name="train-kits23",
        remote_script="train.sh",
        state=state,
        exit_code="-" if finished_at == "-" else "0",
        finished_at=finished_at,
        last_polled_at="2026-05-12T09:35:00",
        input_method="hpc_submit_poll_fetch",
        submit_argv="train.sbatch --fold 0",
        root=root,
    )
    registry.add(job)
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.meta").write_text("script_args=--fold 0\n", encoding="utf-8")
    (job_dir / "worker.meta").write_text("worker_state=running\n", encoding="utf-8")


def write_poll_script(path: Path, polled_at: str) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "job_id=\"$1\"\n"
        "registry=\"${AGENT_HPC_LOG_ROOT}/job_registry.tsv\"\n"
        "calls=\"${AGENT_HPC_LOG_ROOT}/poll.calls\"\n"
        "awk -F'\\t' -v OFS='\\t' -v j=\"$job_id\" -v p=\"" + polled_at + "\" '{ if ($1 == j) $9 = p; print }' \"$registry\" > \"${registry}.tmp\"\n"
        "mv \"${registry}.tmp\" \"$registry\"\n"
        "printf '%s\\n' \"$job_id\" >> \"$calls\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def poll_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["AGENT_HPC_LOG_ROOT"] = str(root)
    return env


def test_selected_job_detail_survives_background_activity(tmp_path: Path) -> None:
    registry_root = tmp_path / "logs"
    state_dir = tmp_path / "state"
    write_job(registry_root, "12345", "RUNNING")
    app = build_app(state_dir, registry_root=registry_root)
    app.state.dashboard.actions.label = "refresh hpc state"
    app.state.dashboard.actions.detail = "rc=0"
    app.state.dashboard.actions.started_at = "12/05/2026 10:00:00"
    app.state.dashboard.actions.finished_at = "12/05/2026 10:01:00"
    app.state.dashboard.actions.log_path.parent.mkdir(parents=True, exist_ok=True)
    app.state.dashboard.actions.log_path.write_text(
        "[12/05/2026 10:00:00] start refresh hpc state: refresh.sh --yes\n"
        "[12/05/2026 10:01:00] done refresh hpc state: rc=0\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.get("/?selected=12345&scope=hpc")

    assert response.status_code == 200
    assert "Background activity" in response.text
    assert "Job details" in response.text
    assert "stdout" in response.text
    assert "refresh hpc state" in response.text
    assert "Selected job owns this pane." in response.text


def test_run_poll_jobs_updates_registry_synchronously(tmp_path: Path) -> None:
    registry_root = tmp_path / "logs"
    write_job(registry_root, "12345", "RUNNING")
    script = write_poll_script(tmp_path / "poll-one.sh", "2026-05-12T09:40:00")

    message = run_poll_jobs(["12345"], script, poll_env(registry_root))

    assert message == "Polled 12345."
    assert JobRegistry(registry_root).find("12345").last_polled_at == "2026-05-12T09:40:00"


def test_poll_job_route_updates_registry_before_redirect(tmp_path: Path) -> None:
    registry_root = tmp_path / "logs"
    state_dir = tmp_path / "state"
    write_job(registry_root, "12345", "RUNNING")
    app = build_app(state_dir, registry_root=registry_root)
    app.state.dashboard.poll_script = write_poll_script(tmp_path / "poll-route.sh", "2026-05-12T09:41:00")
    app.state.dashboard.poll_env = poll_env(registry_root)

    client = TestClient(app)
    response = client.post(
        "/actions/job/12345/poll",
        data={
            "selected": "12345",
            "tab": "active",
            "sort": "submitted_at",
            "direction": "desc",
            "limit": "30",
            "scope": "hpc",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "selected=12345" in response.headers["location"]
    assert JobRegistry(registry_root).find("12345").last_polled_at == "2026-05-12T09:41:00"


def test_poll_all_active_iterates_same_poll_core(tmp_path: Path) -> None:
    registry_root = tmp_path / "logs"
    state_dir = tmp_path / "state"
    write_job(registry_root, "12345", "RUNNING")
    write_job(registry_root, "23456", "PENDING")
    app = build_app(state_dir, registry_root=registry_root)
    app.state.dashboard.poll_script = write_poll_script(tmp_path / "poll-all.sh", "2026-05-12T09:42:00")
    app.state.dashboard.poll_env = poll_env(registry_root)

    client = TestClient(app)
    response = client.post(
        "/actions/global/poll-all-active",
        data={"scope": "hpc"},
        follow_redirects=False,
    )

    calls_path = registry_root / "poll.calls"
    assert response.status_code == 303
    assert response.headers["location"].endswith("message=Polled+2+jobs.")
    assert calls_path.read_text(encoding="utf-8").splitlines() == ["23456", "12345"]
