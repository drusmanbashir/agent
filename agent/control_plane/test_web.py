from __future__ import annotations

from fastapi.testclient import TestClient

from agent.control_plane.models import BLOCKED, STATUSES, StatusResult, TIMED_OUT
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
        "train_indices": 24,
        "val_every_n_epochs": 5,
        "learning_rate": "0.0003",
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
                "train_indices": 24,
                "val_every_n_epochs": 5,
                "learning_rate": "0.0003",
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
            "train_indices": 24,
            "val_every_n_epochs": 5,
            "learning_rate": "0.0003",
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
    assert calls[0]["learning_rate"] == 0.0003
    assert calls[0]["run_name"] is None
