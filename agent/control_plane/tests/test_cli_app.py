from __future__ import annotations

import agent.control_plane.cli_app as cli_app


def test_parse_train_intent_is_deterministic_and_keeps_ollama_metadata() -> None:
    payload = cli_app.parse_train_intent("train kits23 plan 3 fold 0 lr 0.01 val 2 indices 40 hpc run smoke")

    assert payload["intent"] == "train"
    assert payload["project_title"] == "kits23"
    assert payload["plan"] == 3
    assert payload["mode"] == "hpc"
    assert payload["fold"] == 0
    assert payload["learning_rate"] == 0.01
    assert payload["val_every_n_epochs"] == 2
    assert payload["train_indices"] == 40
    assert payload["run_name"] == "smoke"
    assert payload["provider_metadata"]["provider"] == "ollama"
    assert payload["provider_metadata"]["model_call"] is False


def test_ask_preview_does_not_submit(monkeypatch) -> None:
    calls = []

    def fake_train_plan_ready(project_title: str, plan: int, mode: str) -> dict[str, object]:
        return {
            "target": "train",
            "name": project_title,
            "mode": mode,
            "status": "ready",
            "breakpoint": None,
            "message": "ready",
            "details": {"plan": plan},
        }

    def fake_submit(**kwargs) -> dict[str, object]:
        calls.append(kwargs)
        return {"status": "submitted"}

    monkeypatch.setattr(cli_app, "train_plan_ready", fake_train_plan_ready)
    monkeypatch.setattr(cli_app, "orchestrator_train_request", fake_submit)

    payload = cli_app.ask_text("train kits23 plan 3 fold 0")

    assert payload["status"] == "preview"
    assert payload["submit"] is False
    assert payload["intent"]["learning_rate"] == 0.01
    assert payload["intent"]["val_every_n_epochs"] == 2
    assert payload["decision"]["action"] == "submit_local_train"
    assert calls == []


def test_ask_submit_delegates_to_orchestrator(monkeypatch) -> None:
    calls = []

    def fake_submit(**kwargs) -> dict[str, object]:
        calls.append(kwargs)
        return {"status": "submitted", "job_id": "local-1"}

    monkeypatch.setattr(cli_app, "orchestrator_train_request", fake_submit)

    payload = cli_app.ask_text("train kits23 plan 3 fold 0", submit=True)

    assert payload["status"] == "submitted"
    assert calls[0]["project_title"] == "kits23"
    assert calls[0]["plan"] == 3
    assert calls[0]["fold"] == 0
    assert calls[0]["learning_rate"] == 0.01
    assert calls[0]["val_every_n_epochs"] == 2
    assert calls[0]["provider"] == "ollama"


def test_logs_default_to_last_stdout(monkeypatch) -> None:
    def fake_local_job_list(limit: int) -> dict[str, object]:
        return {"jobs": [{"job_id": "local-1"}]}

    def fake_local_job_crash_packet(job_id: str, tail_lines: int) -> dict[str, object]:
        return {
            "job_id": job_id,
            "status": "completed",
            "stdout_tail": ["ok"],
            "stderr_tail": [],
            "log_root": "/tmp/logs",
            "registry_path": "/tmp/logs/job_registry.tsv",
        }

    monkeypatch.setattr(cli_app, "local_job_list", fake_local_job_list)
    monkeypatch.setattr(cli_app, "local_job_crash_packet", fake_local_job_crash_packet)

    payload = cli_app.log_payload("last", "stdout")

    assert payload["job_id"] == "local-1"
    assert payload["stream"] == "stdout"
    assert payload["lines"] == ["ok"]
