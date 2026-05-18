from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import agent.control_plane.hpc as hpc
import agent.control_plane.local_registry as local_registry
from agent.control_plane.local_registry import (
    _submit_local_train_retry_job,
    build_local_job_crash_packet,
    default_local_log_root,
    job_registry,
    logs_root,
    poll_local_job,
)


def _write_fake_train_script(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "print('fake-train-start')",
                "print('argv=' + ' '.join(sys.argv[1:]))",
                "if os.environ.get('AGENT_TEST_FAIL') == '1':",
                "    print('simulated failure', file=sys.stderr)",
                "    raise SystemExit(7)",
                "print('fake-train-success')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _wait_for_terminal(job_id: str, root: Path) -> dict[str, object]:
    for _ in range(50):
        payload = poll_local_job(job_id, root=root)
        if payload["status"] not in {"submitted", "running"}:
            return payload
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def test_local_train_retry_submission_and_completion(tmp_path: Path, monkeypatch) -> None:
    logs_root = tmp_path / "logs"
    train_script = tmp_path / "fake_train_retry.py"
    _write_fake_train_script(train_script)
    monkeypatch.delenv("AGENT_TEST_FAIL", raising=False)

    job = _submit_local_train_retry_job(
        project_title="kits2",
        plan=3,
        fold=1,
        root=logs_root,
        python_bin=Path(sys.executable),
        train_script=train_script,
        run_cwd=tmp_path,
        pythonpath_roots=[],
        provider="ollama",
        model="llama3.1",
        escalation_target="human-review",
    )

    payload = _wait_for_terminal(job.job_id, logs_root)
    assert payload["status"] == "completed"
    assert payload["job"]["log_root"] == str(logs_root)

    registry_job = job_registry(logs_root).find(job.job_id)
    assert registry_job is not None
    assert registry_job.state == "COMPLETED"
    assert registry_job.exit_code == "0"
    assert registry_job.stdout_path.exists()
    assert registry_job.stderr_path.exists()
    assert registry_job.job_meta_path.exists()
    assert registry_job.worker_meta_path.exists()
    assert registry_job.orch_path.exists()
    orch = json.loads(registry_job.orch_path.read_text(encoding="utf-8"))
    assert orch["provider"] == "ollama"
    assert orch["model"] == "llama3.1"
    assert orch["escalation_target"] == "human-review"
    assert "fake-train-success" in registry_job.stdout_path.read_text(encoding="utf-8")


def test_local_train_retry_failure_crash_packet(tmp_path: Path, monkeypatch) -> None:
    logs_root = tmp_path / "logs"
    train_script = tmp_path / "fake_train_retry.py"
    _write_fake_train_script(train_script)
    monkeypatch.setenv("AGENT_TEST_FAIL", "1")

    job = _submit_local_train_retry_job(
        project_title="lits",
        plan=7,
        root=logs_root,
        python_bin=Path(sys.executable),
        train_script=train_script,
        run_cwd=tmp_path,
        pythonpath_roots=[],
        provider="ollama",
        model="mistral",
        escalation_target="gpu-owner",
    )

    payload = _wait_for_terminal(job.job_id, logs_root)
    assert payload["status"] == "failed"

    crash_packet = build_local_job_crash_packet(job.job_id, root=logs_root)
    assert crash_packet["status"] == "failed"
    assert crash_packet["log_root"] == str(logs_root)
    assert crash_packet["orchestrator"]["provider"] == "ollama"
    assert crash_packet["orchestrator"]["model"] == "mistral"
    assert crash_packet["orchestrator"]["escalation_target"] == "gpu-owner"
    assert "simulated failure" in "\n".join(crash_packet["stderr_tail"])


def test_logs_root_uses_storage_roots_config(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "local"
    monkeypatch.setattr(local_registry, "storage_root", lambda name: configured)

    assert default_local_log_root() == configured
    assert logs_root() == configured
    assert configured.exists()


def test_dashboard_context_points_to_fran_jobs_page(monkeypatch) -> None:
    monkeypatch.setenv("FRAN_JOBS_PAGE_URL", "http://fran.local/jobs")
    monkeypatch.setattr(hpc, "storage_root", lambda name: Path("/s/agent_rw/logs/hpc"))

    payload = hpc.dashboard_context()

    assert payload["message"] == "FRAN webapp jobs page is the canonical status surface for submitted HPC jobs."
    assert payload["start_command"] == "python -m webbrowser http://fran.local/jobs"
    assert payload["status_command"] == "open http://fran.local/jobs to inspect job status in the FRAN webapp"
    assert payload["url_command"] == "echo http://fran.local/jobs"
    assert payload["url"] == "http://fran.local/jobs"
