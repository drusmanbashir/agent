from __future__ import annotations

from fastapi.testclient import TestClient

from agent.control_plane.models import BLOCKED, STATUSES, StatusResult, TIMED_OUT
import agent.control_plane.service as service
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


def test_base_context_includes_local_train_defaults(monkeypatch) -> None:
    monkeypatch.setattr(web, "dashboard_context", lambda: {"message": "ready", "start_command": "start", "status_command": "status", "url_command": "url", "url": None})
    monkeypatch.setattr(web, "list_existing_projects", lambda: [{"name": "kits23"}])

    context = web.base_context(object())

    assert context["local_train_form"] == {
        "project": "kits23",
        "plan_id": 3,
        "fold": 0,
        "train_indices": None,
        "val_every_n_epochs": 2,
        "learning_rate": "0.01",
        "run_name": "none",
    }
    assert context["local_train_api"] == {
        "submit": "/api/orchestrator/requests/train",
        "jobs": "/api/local-train/jobs",
        "job_detail_prefix": "/api/local-train/jobs",
        "orchestrator": "/api/local-train/orchestrator",
        "orchestrator_message": "/api/local-train/orchestrator/messages",
    }


def test_index_renders_local_train_slice(monkeypatch) -> None:
    def fake_base_context(request) -> dict:
        return {
            "request": request,
            "dashboard": {
                "message": "ready",
                "start_command": "start",
                "status_command": "status",
                "url_command": "url",
                "url": None,
            },
            "projects": [{"name": "kits23"}],
            "active_tab": "local-train",
            "local_train_form": {
                "project": "kits23",
                "plan_id": 3,
                "fold": 0,
                "train_indices": None,
                "val_every_n_epochs": 2,
                "learning_rate": "0.01",
                "run_name": "none",
            },
            "local_train_api": {
                "submit": "/api/orchestrator/requests/train",
                "jobs": "/api/local-train/jobs",
                "job_detail_prefix": "/api/local-train/jobs",
                "orchestrator": "/api/local-train/orchestrator",
                "orchestrator_message": "/api/local-train/orchestrator/messages",
            },
            "datasource_form": {"name": "", "mode": "local", "ensure": False, "num_processes": 1, "job_id": ""},
            "project_form": {
                "title": "",
                "mnemonic": "",
                "datasources": "",
                "mode": "local",
                "ensure": False,
                "num_processes": 1,
                "test": False,
                "job_id": "",
            },
            "datasource_result": None,
            "project_result": None,
        }

    monkeypatch.setattr(web, "base_context", fake_base_context)

    client = TestClient(web.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Local Train" in response.text
    assert "ACP" in response.text
    assert "Ask ACP to resolve train prerequisites first" in response.text
    assert "Use kits23 plan 3 test" in response.text
    assert 'data-orchestrator-request-api="/api/orchestrator/requests/train"' in response.text
    assert 'data-train-jobs-api="/api/local-train/jobs"' in response.text
    assert 'data-train-orchestrator-api="/api/local-train/orchestrator"' in response.text
    assert 'value="kits23"' in response.text
    assert 'value="3"' in response.text


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
