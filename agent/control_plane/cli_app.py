from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from agent.control_plane.ollama_orchestrator import decide_train_workflow
from agent.control_plane.service import (
    local_job_crash_packet,
    local_job_list,
    local_job_status,
    local_orchestrator_status,
    orchestrator_train_request,
    train_plan_ready,
)

LOG_STREAMS = {"stdout", "stderr"}


def provider_metadata() -> dict[str, object]:
    return {
        "provider": "ollama",
        "model": "",
        "parse_path": "deterministic_narrow",
        "model_call": False,
        "message": "No Ollama/LangChain model call is wired here; parsing is deterministic and narrow.",
    }


def _match_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return None
    return int(match[1])


def _match_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return None
    return float(match[1])


def parse_train_intent(text: str) -> dict[str, object]:
    project_match = re.search(r"(?:train|project)\s+([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
    plan = _match_int(r"(?:plan|p)\s*[:=]?\s*(\d+)", text)
    if project_match is None or plan is None:
        return {
            "intent": "unknown",
            "text": text,
            "provider_metadata": provider_metadata(),
            "message": "Expected a narrow train intent like: train kits23 plan 3 fold 0 lr 0.01 val 2.",
        }

    mode = "hpc" if re.search(r"\bhpc\b", text, flags=re.IGNORECASE) else "local"
    run_name_match = re.search(r"(?:run_name|run)\s*[:=]?\s*([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
    return {
        "intent": "train",
        "project_title": project_match[1],
        "plan": plan,
        "mode": mode,
        "fold": _match_int(r"(?:fold|f)\s*[:=]?\s*(\d+)", text),
        "learning_rate": _match_float(r"(?:learning_rate|lr)\s*[:=]?\s*([0-9.eE+-]+)", text) or 0.01,
        "train_indices": _match_int(r"(?:train_indices|indices)\s*[:=]?\s*(\d+)", text),
        "val_every_n_epochs": _match_int(r"(?:val_every_n_epochs|val_every|val)\s*[:=]?\s*(\d+)", text) or 2,
        "run_name": None if run_name_match is None or run_name_match[1] == "none" else run_name_match[1],
        "provider_metadata": provider_metadata(),
    }


def preview_train_intent(intent: dict[str, object]) -> dict[str, object]:
    readiness = train_plan_ready(
        project_title=str(intent["project_title"]),
        plan=int(intent["plan"]),
        mode=str(intent["mode"]),
    )
    decision = decide_train_workflow(
        project_title=str(intent["project_title"]),
        plan=int(intent["plan"]),
        readiness=readiness,
        provider="ollama",
        model="",
    )
    return {
        "status": "preview",
        "submit": False,
        "intent": intent,
        "decision": decision,
        "readiness": readiness,
        "provider_metadata": provider_metadata(),
    }


def submit_train_intent(intent: dict[str, object]) -> dict[str, object]:
    return orchestrator_train_request(
        project_title=str(intent["project_title"]),
        plan=int(intent["plan"]),
        mode=str(intent["mode"]),
        fold=int(intent["fold"]) if intent["fold"] is not None else None,
        learning_rate=float(intent["learning_rate"]) if intent["learning_rate"] is not None else None,
        train_indices=int(intent["train_indices"]) if intent["train_indices"] is not None else None,
        val_every_n_epochs=int(intent["val_every_n_epochs"]),
        run_name=str(intent["run_name"]) if intent["run_name"] is not None else None,
        provider="ollama",
        model="",
    )


def ask_text(text: str, submit: bool = False) -> dict[str, object]:
    intent = parse_train_intent(text)
    if intent["intent"] != "train":
        return intent
    if submit:
        payload = submit_train_intent(intent)
        payload["provider_metadata"] = provider_metadata()
        return payload
    return preview_train_intent(intent)


def last_job_id() -> str:
    jobs = local_job_list(limit=1)["jobs"]
    if not jobs:
        raise SystemExit("No local ACP jobs found.")
    return str(jobs[0]["job_id"])


def resolve_job_id(job_id: str) -> str:
    if job_id == "last":
        return last_job_id()
    return job_id


def observe_job(job_id: str) -> dict[str, object]:
    return local_job_status(resolve_job_id(job_id))


def log_payload(job_id: str, stream: str, tail_lines: int = 200) -> dict[str, object]:
    packet = local_job_crash_packet(resolve_job_id(job_id), tail_lines=tail_lines)
    key = f"{stream}_tail"
    return {
        "job_id": packet["job_id"],
        "status": packet["status"],
        "stream": stream,
        "lines": packet[key],
        "log_root": packet["log_root"],
        "registry_path": packet["registry_path"],
    }


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_status(_args: argparse.Namespace) -> int:
    print_json(local_orchestrator_status())
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    print_json(ask_text(" ".join(args.text), submit=args.submit))
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    print_json(observe_job(args.job_id))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    job_id = "last" if args.job_id in LOG_STREAMS else args.job_id
    stream = args.job_id if args.job_id in LOG_STREAMS else args.stream
    print_json(log_payload(job_id, stream, tail_lines=args.tail_lines))
    return 0


def terminal() -> int:
    last_intent: dict[str, object] | None = None
    print("ACP terminal. Deterministic narrow parser; provider metadata remains ollama. Type exit to quit.")
    while True:
        line = input("acp> ").strip()
        if line in {"exit", "quit"}:
            return 0
        if not line:
            continue
        if line == "status":
            print_json(local_orchestrator_status())
            continue
        if line == "submit":
            if last_intent is None:
                print("No parsed train intent to submit.")
                continue
            print_json(submit_train_intent(last_intent))
            last_intent = None
            continue
        parts = line.split()
        if parts[0] == "observe":
            job_id = parts[1] if len(parts) > 1 else "last"
            print_json(observe_job(job_id))
            continue
        if parts[0] == "logs":
            stream = parts[1] if len(parts) > 1 and parts[1] in LOG_STREAMS else "stdout"
            job_id = parts[2] if len(parts) > 2 else "last"
            print_json(log_payload(job_id, stream))
            continue
        if parts[0] == "ask":
            line = line.removeprefix("ask").strip()
        intent = parse_train_intent(line)
        if intent["intent"] == "train":
            last_intent = intent
            print_json(preview_train_intent(intent))
            continue
        print_json(intent)


def cmd_terminal(_args: argparse.Namespace) -> int:
    return terminal()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="acp", description="Minimal ACP operator CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Preview a narrow train intent; use --submit for execution.")
    ask.add_argument("--submit", action="store_true")
    ask.add_argument("text", nargs="+")
    ask.set_defaults(func=cmd_ask)

    status = sub.add_parser("status", help="Show ACP orchestrator status.")
    status.set_defaults(func=cmd_status)

    observe = sub.add_parser("observe", help="Observe a local ACP job.")
    observe.add_argument("job_id", nargs="?", default="last")
    observe.set_defaults(func=cmd_observe)

    logs = sub.add_parser("logs", help="Show stdout/stderr tail for a local ACP job.")
    logs.add_argument("job_id", nargs="?", default="last")
    logs.add_argument("stream", nargs="?", choices=sorted(LOG_STREAMS), default="stdout")
    logs.add_argument("--tail-lines", type=int, default=200)
    logs.set_defaults(func=cmd_logs)

    terminal_cmd = sub.add_parser("terminal", aliases=["repl"], help="Start ACP REPL.")
    terminal_cmd.set_defaults(func=cmd_terminal)

    stdio = sub.add_parser("stdio", help="Start ACP MCP stdio server.")
    stdio.set_defaults(func=lambda _args: mcp_stdio())
    return parser


def mcp_stdio() -> int:
    from agent.control_plane.mcp_server import main

    main()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
