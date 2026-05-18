from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from agent.control_plane.models import BLOCKED, STATUSES, StatusResult, TIMED_OUT
import agent.control_plane.service as service
from agent.hpc.cli.hpc_dashboard_web import POLL_SCRIPT
from agent.hpc.tools.job_registry import JobRecord, JobRegistry
import agent.control_plane.web as web


def test_status_result_to_dict_omits_none_fields() -> None:
    payload = StatusResult(
        target="train",
        name="kits23",
        mode="local",
        status=TIMED_OUT,
        message="Timed out waiting for prerequisite completion.",
        details={"poll_url": "/api/local-train/jobs/local-123"},
        next_action="poll",
    ).to_dict()

    assert payload == {
        "target": "train",
        "name": "kits23",
        "mode": "local",
        "status": "timed_out",
        "message": "Timed out waiting for prerequisite completion.",
        "details": {"poll_url": "/api/local-train/jobs/local-123"},
        "next_action": "poll",
    }
    assert BLOCKED in STATUSES
    assert TIMED_OUT in STATUSES


def test_jobs_home_renders_dashboard_layout(monkeypatch) -> None:
    def fake_jobs_page_context(request, selected="", tab="active", sort="", direction="desc", limit="30", scope="hpc", message="") -> dict:
        return {
            "request": request,
            "title": "Jobs",
            "nav_page": "jobs",
            "message": "Jobs ready",
            "view": {"selected": "", "tab": "active", "sort": "", "direction": "desc", "limit": "30", "scope": "hpc"},
            "jobs": [],
            "active_jobs": [],
            "closed_jobs": [],
            "selected_job": None,
            "summary_pairs": [],
            "job_meta_pairs": [],
            "worker_meta_pairs": [],
            "activity": {"running": False, "label": "idle", "started_at": "-", "finished_at": "-", "detail": ""},
            "activity_output": "",
            "limit_options": ("30", "50", "100", "all"),
            "registry_path": "/tmp/job_registry.tsv",
        }

    monkeypatch.setattr(web, "jobs_page_context", fake_jobs_page_context)

    client = TestClient(web.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "HPC Jobs Dashboard" in response.text
    assert "Background activity" in response.text
    assert "Poll all active jobs" in response.text
    assert "No active jobs in hpc scope." in response.text
    assert "Dashboard" in response.text
    assert "Projects" in response.text
    assert "Training" in response.text
    assert "Jobs ready" in response.text


def test_projects_page_renders_project_tools_without_ollama(monkeypatch) -> None:
    monkeypatch.setattr(web, "list_existing_projects", lambda: [{"name": "kits23"}])

    client = TestClient(web.app)
    response = client.get("/projects?mode=hpc")

    assert response.status_code == 200
    assert "Projects" in response.text
    assert "Inspect project" in response.text
    assert "Loaded project" in response.text
    assert "Project readiness" in response.text
    assert "Datasource readiness" in response.text
    assert "Ollama" not in response.text
    assert 'name="mode" value="hpc"' in response.text
    assert "kits23" in response.text


def test_project_ready_view_preserves_selected_mode(monkeypatch) -> None:
    monkeypatch.setattr(web, "list_existing_projects", lambda: [])

    def fake_project_ready(*args, **kwargs) -> dict[str, object]:
        return {"status": "ready", "target": "project", "mode": "hpc", "next_action": None}

    monkeypatch.setattr(web, "project_ready", fake_project_ready)

    client = TestClient(web.app)
    response = client.post(
        "/project/ready",
        data={
            "title": "kits23",
            "mnemonic": "k23",
            "datasources": "ds1,ds2",
            "mode": "hpc",
            "num_processes": "2",
            "job_id": "",
        },
    )

    assert response.status_code == 200
    assert "Project check complete." in response.text
    assert 'name="mode" value="hpc"' in response.text


def test_training_page_renders_placeholder() -> None:
    client = TestClient(web.app)
    response = client.get("/training")
    alias = client.get("/train")

    assert response.status_code == 200
    assert alias.status_code == 200
    assert "Training" in response.text
    assert "Training" in alias.text
    assert "Training arguments, submit controls, and live progress will land here next." in response.text
    assert "Back to dashboard" in response.text


def test_ollama_prompt_api_delegates(monkeypatch) -> None:
    calls = []

    def fake_ollama_prompt(prompt: str, model: str) -> dict[str, object]:
        calls.append({"prompt": prompt, "model": model})
        return {"target": "ollama", "name": model, "mode": "local", "status": "ready", "message": "ok"}

    monkeypatch.setattr(web, "ollama_prompt", fake_ollama_prompt)

    client = TestClient(web.app)
    response = client.post("/api/ollama/prompt", json={"prompt": "summarize kits23", "model": "llama3.1"})

    assert response.status_code == 200
    assert response.json() == {"target": "ollama", "name": "llama3.1", "mode": "local", "status": "ready", "message": "ok"}
    assert calls == [{"prompt": "summarize kits23", "model": "llama3.1"}]


def test_orchestrator_train_request_route_delegates(monkeypatch) -> None:
    calls = []

    def fake_orchestrator_train_request(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "target": "train",
            "name": kwargs["project_title"],
            "mode": "local",
            "status": "blocked",
            "breakpoint": "preproc",
            "message": "Project needs preprocessing before train.",
            "details": {"plan_id": kwargs["plan"]},
        }

    monkeypatch.setattr(web, "orchestrator_train_request", fake_orchestrator_train_request)

    client = TestClient(web.app)
    response = client.post(
        "/api/orchestrator/requests/train",
        json={
            "project": "kits23",
            "plan_id": 3,
            "mode": "hpc",
            "fold": 0,
            "train_indices": None,
            "run_name": "none",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "target": "train",
        "name": "kits23",
        "mode": "local",
        "status": "blocked",
        "message": "Project needs preprocessing before train.",
        "details": {"plan_id": 3, "breakpoint": "preproc"},
        "next_action": "preproc",
    }
    assert calls[0]["project_title"] == "kits23"
    assert calls[0]["plan"] == 3
    assert calls[0]["mode"] == "hpc"
    assert calls[0]["learning_rate"] == 0.01
    assert calls[0]["val_every_n_epochs"] == 2
    assert calls[0]["run_name"] is None


def test_local_job_detail_exposes_acp_provenance(monkeypatch) -> None:
    def fake_crash_packet(job_id: str, tail_lines: int) -> dict:
        return {
            "job_id": job_id,
            "status": "running",
            "message": "Job is running locally.",
            "job": {
                "job_id": job_id,
                "job_name": "train_kits23_p3_f0",
                "submitted_at": "2026-05-06T10:00:00+01:00",
                "finished_at": "-",
                "last_polled_at": "2026-05-06T10:01:00+01:00",
                "job_dir": "/tmp/local-123",
                "stdout": "/tmp/local-123/std.out",
                "stderr": "/tmp/local-123/std.err",
            },
            "job_meta": {
                "job_name": "train_kits23_p3_f0",
                "input_method": "local_train_retry",
                "submit_argv": "python train_retry.py --project kits23",
                "project_title": "kits23",
                "plan": "3",
                "fold": "0",
                "run_name": "none",
            },
            "worker_meta": {
                "worker_state": "running",
            },
            "orchestrator": {
                "provider": "ollama",
                "model": "mistral",
                "escalation_target": "gpu-owner",
            },
            "stderr_tail": ["stderr tail"],
            "note_context": "note",
        }

    monkeypatch.setattr(service, "build_local_job_crash_packet", fake_crash_packet)

    detail = service.local_job_detail("local-123")

    assert detail["summary_text"] == "\n".join(
        [
            "job=local-123",
            "job_name=train_kits23_p3_f0",
            "input_method=local_train_retry",
            "project=kits23",
            "plan=3",
            "fold=0",
            "run_name=none",
            "worker_state=running",
            "acp_provider=ollama",
            "acp_model=mistral",
            "acp_escalation_target=gpu-owner",
        ]
    )
    assert detail["input_command"] == "python train_retry.py --project kits23"
    assert detail["input_method"] == "local_train_retry"
    assert detail["job_name"] == "train_kits23_p3_f0"
    assert detail["acp"] == {"provider": "ollama", "model": "mistral", "escalation_target": "gpu-owner"}
    assert detail["provenance"]["job_meta"]["project_title"] == "kits23"


def write_hpc_job(root: Path, job_id: str, state: str, finished_at: str = "-") -> None:
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


def write_poll_script(path: Path, polled_at: str) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "job_id=\"$1\"\n"
        "registry=\"${AGENT_HPC_LOG_ROOT}/job_registry.tsv\"\n"
        "awk -F'\\t' -v OFS='\\t' -v j=\"$job_id\" -v p=\"" + polled_at + "\" '{ if ($1 == j) $9 = p; print }' \"$registry\" > \"${registry}.tmp\"\n"
        "mv \"${registry}.tmp\" \"$registry\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_control_plane_poll_job_updates_registry_before_redirect(tmp_path: Path) -> None:
    registry_root = tmp_path / "logs"
    state_dir = tmp_path / "state"
    write_hpc_job(registry_root, "12345", "RUNNING")
    script = write_poll_script(tmp_path / "poll-control.sh", "2026-05-12T09:43:00")
    env = dict(os.environ)
    env["AGENT_HPC_LOG_ROOT"] = str(registry_root)
    web.jobs_runtime = web.DashboardRuntime(JobRegistry(registry_root), web.ActionRunner(state_dir), web.templates, POLL_SCRIPT)
    web.jobs_runtime.poll_script = script
    web.jobs_runtime.poll_env = env

    client = TestClient(web.app)
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
    assert JobRegistry(registry_root).find("12345").last_polled_at == "2026-05-12T09:43:00"
    web.jobs_runtime = None
