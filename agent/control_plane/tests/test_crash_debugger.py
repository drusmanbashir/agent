from __future__ import annotations

from pathlib import Path

from agent.control_plane.crash_debugger import CrashDebugger, load_debug_tool_registry, match_registered_tools


def test_registry_match_is_deterministic() -> None:
    packet = {
        "job_id": "local-11",
        "log_root": "/tmp/logs",
        "stage": "train",
        "failure_class": "launch_failure",
        "message": "train launch failed",
        "stderr_tail": ["ModuleNotFoundError: No module named fran"],
        "stdout_tail": [],
        "job_meta": {},
        "worker_meta": {},
    }

    tools = load_debug_tool_registry()
    matches = match_registered_tools(packet, tools)

    assert [item["name"] for item in matches] == ["fran_import_sanity"]


def test_fallback_routes_to_codex_when_no_tool_matches(tmp_path: Path, monkeypatch) -> None:
    debugger = CrashDebugger()

    def fake_ollama(packet, tools):
        return {
            "summary": "No registered tool fits this crash.",
            "confidence": 0.31,
            "matched_tool": None,
            "raw": {"tool_name": "", "confidence": 0.31},
        }

    def fake_workspace(packet, job_log_root=None, attempt=1):
        return {
            "job_id": packet["job_id"],
            "attempt": attempt,
            "plan_root": str(tmp_path / "codex_repair"),
            "branch": "codex/local-12/1",
            "agent": {"worktree_path": str(tmp_path / "agent")},
            "fran": {"worktree_path": str(tmp_path / "fran")},
            "codex_command": ["codex", "exec", "-m", "gpt-5.4"],
        }

    monkeypatch.setattr(CrashDebugger, "_ollama_triage", lambda self, packet, tools: fake_ollama(packet, tools))
    monkeypatch.setattr(
        CrashDebugger,
        "plan_repair_workspace",
        lambda self, packet, job_log_root=None, attempt=1: fake_workspace(packet, job_log_root, attempt),
    )

    payload = debugger.debug_packet(
        {
            "job_id": "local-12",
            "log_root": str(tmp_path),
            "stage": "train",
            "failure_class": "train_failure",
            "message": "unknown train failure",
            "stderr_tail": ["RuntimeError: strange crash"],
            "stdout_tail": [],
            "job_meta": {},
            "worker_meta": {},
        }
    )

    assert payload["route"] == "codex_cli"
    assert payload["workspace"]["branch"] == "codex/local-12/1"
    assert payload["workspace"]["codex_command"][:4] == ["codex", "exec", "-m", "gpt-5.4"]


def test_worktree_planning_creates_paths_under_job_log_root(tmp_path: Path, monkeypatch) -> None:
    debugger = CrashDebugger()
    calls: list[list[str]] = []

    def fake_run(argv, check, capture_output, text):
        calls.append(argv)
        if argv[3:5] == ["rev-parse", "HEAD"]:
            class Result:
                stdout = "abc123\n"

            return Result()
        if argv[3:6] == ["worktree", "add", "--detach"]:
            Path(argv[6]).mkdir(parents=True, exist_ok=True)

            class Result:
                stdout = ""

            return Result()
        raise AssertionError(argv)

    monkeypatch.setattr("agent.control_plane.crash_debugger.subprocess.run", fake_run)

    workspace = debugger.plan_repair_workspace(
        packet={
            "job_id": "local-13",
            "log_root": str(tmp_path),
            "stage": "train",
            "failure_class": "train_failure",
            "message": "oom",
            "stderr_tail": ["CUDA out of memory"],
            "stdout_tail": [],
            "job_meta": {},
            "worker_meta": {},
        }
    )

    assert workspace["plan_root"] == str(tmp_path / "codex_repair" / "local-13" / "attempt-1")
    assert workspace["agent"]["worktree_path"] == str(tmp_path / "codex_repair" / "local-13" / "attempt-1" / "agent")
    assert workspace["fran"]["worktree_path"] == str(tmp_path / "codex_repair" / "local-13" / "attempt-1" / "fran")
    assert workspace["codex_command"][0:6] == ["codex", "exec", "-m", "gpt-5.4", "-c", 'model_reasoning_effort="medium"']
    assert calls[0][0:4] == ["git", "-C", "/home/ub/code/agent", "rev-parse"]
    assert calls[2][0:4] == ["git", "-C", "/home/ub/code/fran", "rev-parse"]
