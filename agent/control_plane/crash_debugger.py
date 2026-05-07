from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.control_plane.local_registry import build_local_job_crash_packet

DEFAULT_REGISTRY_PATH = Path(__file__).with_name("debug_tool_registry.yaml")
AGENT_REPO = Path("/home/ub/code/agent")
FRAN_REPO = Path("/home/ub/code/fran")
DEFAULT_OLLAMA_MODEL = "llama3.1"


def load_debug_tool_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tools = payload["tools"]
    return sorted(tools, key=lambda item: item["name"])


def build_local_crash_packet(job_id: str, tail_lines: int = 200, root: Path | None = None) -> dict[str, Any]:
    return build_local_job_crash_packet(job_id=job_id, tail_lines=tail_lines, root=root)


def infer_stage(packet: dict[str, Any]) -> str:
    if "stage" in packet and packet["stage"]:
        return str(packet["stage"])
    job_meta = packet.get("job_meta", {})
    submit_argv = str(job_meta.get("submit_argv", ""))
    job_name = str(job_meta.get("job_name", ""))
    combined = f"{job_name}\n{submit_argv}".lower()
    if "analyze_resample" in combined or "preproc" in combined:
        return "preproc"
    if "train" in combined:
        return "train"
    return "unknown"


def classify_failure(packet: dict[str, Any]) -> str:
    if "failure_class" in packet and packet["failure_class"]:
        return str(packet["failure_class"])
    corpus = crash_corpus(packet)
    if "modulenotfounderror" in corpus or "importerror" in corpus:
        return "launch_failure"
    if "no such file or directory" in corpus or "permission denied" in corpus:
        return "launch_failure"
    if "cuda out of memory" in corpus or "cublas_status_alloc_failed" in corpus:
        return "train_failure"
    stage = infer_stage(packet)
    if stage == "preproc":
        return "preproc_failure"
    if stage == "train":
        return "train_failure"
    return "registry_failure"


def crash_corpus(packet: dict[str, Any]) -> str:
    parts = [
        str(packet.get("message", "")),
        str(packet.get("note_context", "")),
        "\n".join(packet.get("stdout_tail", [])),
        "\n".join(packet.get("stderr_tail", [])),
        json.dumps(packet.get("job_meta", {}), sort_keys=True),
        json.dumps(packet.get("worker_meta", {}), sort_keys=True),
    ]
    return "\n".join(parts).lower()


def match_registered_tools(packet: dict[str, Any], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage = infer_stage(packet)
    failure_class = classify_failure(packet)
    corpus = crash_corpus(packet)
    matches = []
    for tool in tools:
        stage_match = stage in tool["stages"]
        failure_match = failure_class in tool["failure_classes"]
        pattern_hits = [pattern for pattern in tool["stderr_patterns"] if pattern.lower() in corpus]
        score = 0
        if stage_match:
            score += 4
        if failure_match:
            score += 4
        score += len(pattern_hits) * 3
        if score == 0 or (tool["stderr_patterns"] and not pattern_hits):
            continue
        matches.append(
            {
                "name": tool["name"],
                "module": tool["module"],
                "runnable": tool["runnable"],
                "score": score,
                "stage_match": stage_match,
                "failure_match": failure_match,
                "pattern_hits": pattern_hits,
                "summary": tool["summary"],
            }
        )
    return sorted(matches, key=lambda item: (-item["score"], item["name"]))


@dataclass(slots=True)
class CrashDebugger:
    registry_path: Path = DEFAULT_REGISTRY_PATH
    agent_repo: Path = AGENT_REPO
    fran_repo: Path = FRAN_REPO
    ollama_model: str = DEFAULT_OLLAMA_MODEL

    def debug_job(
        self,
        job_id: str,
        tail_lines: int = 200,
        job_log_root: str | None = None,
    ) -> dict[str, Any]:
        packet_root = Path(job_log_root) if job_log_root else None
        packet = build_local_crash_packet(job_id=job_id, tail_lines=tail_lines, root=packet_root)
        return self.debug_packet(packet=packet, job_log_root=job_log_root)

    def debug_packet(self, packet: dict[str, Any], job_log_root: str | None = None) -> dict[str, Any]:
        tools = load_debug_tool_registry(self.registry_path)
        matched_tools = match_registered_tools(packet, tools)
        failure_class = classify_failure(packet)
        if matched_tools:
            top = matched_tools[0]
            return {
                "route": "registered_tool",
                "failure_class": failure_class,
                "confidence": min(0.99, 0.55 + (top["score"] * 0.05)),
                "summary": top["summary"],
                "recommended_action": f"Run registered tool {top['runnable']}.",
                "matched_tools": matched_tools,
                "packet": packet,
            }
        triage = self._ollama_triage(packet=packet, tools=tools)
        routed_tool = triage["matched_tool"]
        if routed_tool:
            routed_matches = [item for item in matched_tools if item["name"] == routed_tool["name"]] or [routed_tool]
            return {
                "route": "ollama_registered_tool",
                "failure_class": failure_class,
                "confidence": triage["confidence"],
                "summary": triage["summary"],
                "recommended_action": f"Run registered tool {routed_tool['runnable']}.",
                "matched_tools": routed_matches,
                "packet": packet,
                "ollama": triage["raw"],
            }
        workspace = self.plan_repair_workspace(packet=packet, job_log_root=job_log_root)
        return {
            "route": "codex_cli",
            "failure_class": failure_class,
            "confidence": triage["confidence"],
            "summary": triage["summary"],
            "recommended_action": "Review the planned Codex repair command and run it if escalation is approved.",
            "matched_tools": [],
            "packet": packet,
            "ollama": triage["raw"],
            "workspace": workspace,
        }

    def _ollama_triage(self, packet: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = self._ollama_prompt(packet=packet, tools=tools)
        try:
            result = subprocess.run(
                ["ollama", "run", self.ollama_model, prompt],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return {
                "summary": "Ollama is unavailable; escalate to Codex planning.",
                "confidence": 0.2,
                "matched_tool": None,
                "raw": {"returncode": 127, "stdout": "", "stderr": "ollama not found"},
            }
        stdout = result.stdout.strip()
        if result.returncode != 0 or not stdout:
            return {
                "summary": "Ollama did not produce a usable routing decision.",
                "confidence": 0.2,
                "matched_tool": None,
                "raw": {"returncode": result.returncode, "stdout": stdout, "stderr": result.stderr.strip()},
            }
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "summary": "Ollama returned non-JSON triage output.",
                "confidence": 0.2,
                "matched_tool": None,
                "raw": {"returncode": result.returncode, "stdout": stdout, "stderr": result.stderr.strip()},
            }
        tool_by_name = {tool["name"]: tool for tool in tools}
        tool = tool_by_name.get(payload.get("tool_name", ""))
        matched_tool = None
        if tool is not None:
            matched_tool = {
                "name": tool["name"],
                "module": tool["module"],
                "runnable": tool["runnable"],
                "score": 0,
                "stage_match": infer_stage(packet) in tool["stages"],
                "failure_match": classify_failure(packet) in tool["failure_classes"],
                "pattern_hits": [],
                "summary": tool["summary"],
            }
        return {
            "summary": str(payload.get("summary", "Ollama triage completed.")),
            "confidence": float(payload.get("confidence", 0.35)),
            "matched_tool": matched_tool,
            "raw": payload,
        }

    def _ollama_prompt(self, packet: dict[str, Any], tools: list[dict[str, Any]]) -> str:
        prompt = {
            "instruction": "Return JSON with keys tool_name, summary, confidence. Use an empty tool_name when no registered tool fits.",
            "packet": {
                "job_id": packet.get("job_id", ""),
                "message": packet.get("message", ""),
                "stage": infer_stage(packet),
                "failure_class": classify_failure(packet),
                "stderr_tail": packet.get("stderr_tail", []),
            },
            "tools": [
                {
                    "name": tool["name"],
                    "summary": tool["summary"],
                    "stages": tool["stages"],
                    "failure_classes": tool["failure_classes"],
                    "stderr_patterns": tool["stderr_patterns"],
                }
                for tool in tools
            ],
        }
        return json.dumps(prompt, indent=2, sort_keys=True)

    def plan_repair_workspace(self, packet: dict[str, Any], job_log_root: str | None = None, attempt: int = 1) -> dict[str, Any]:
        packet_job_id = str(packet["job_id"])
        log_root = Path(job_log_root or str(packet["log_root"]))
        plan_root = log_root / "codex_repair" / packet_job_id / f"attempt-{attempt}"
        plan_root.mkdir(parents=True, exist_ok=True)
        agent_worktree = self._create_repo_worktree(self.agent_repo, plan_root / "agent")
        fran_worktree = self._create_repo_worktree(self.fran_repo, plan_root / "fran")
        prompt_path = plan_root / "codex_prompt.txt"
        prompt_path.write_text(self._codex_prompt(packet, agent_worktree, fran_worktree), encoding="utf-8")
        output_path = plan_root / "codex_last_message.txt"
        command = [
            "codex",
            "exec",
            "-m",
            "gpt-5.4",
            "-c",
            'model_reasoning_effort="medium"',
            "--sandbox",
            "danger-full-access",
            "--ask-for-approval",
            "never",
            "--cd",
            agent_worktree["worktree_path"],
            "--add-dir",
            fran_worktree["worktree_path"],
            "--output-last-message",
            str(output_path),
            str(prompt_path),
        ]
        return {
            "job_id": packet_job_id,
            "attempt": attempt,
            "plan_root": str(plan_root),
            "branch": f"codex/{packet_job_id}/{attempt}",
            "agent": agent_worktree,
            "fran": fran_worktree,
            "codex_prompt_path": str(prompt_path),
            "codex_output_path": str(output_path),
            "codex_command": command,
        }

    def _create_repo_worktree(self, repo_path: Path, worktree_path: Path) -> dict[str, Any]:
        head = (
            subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
        )
        if not worktree_path.exists():
            subprocess.run(
                ["git", "-C", str(repo_path), "worktree", "add", "--detach", str(worktree_path), head],
                check=True,
                capture_output=True,
                text=True,
            )
        return {
            "source_repo": str(repo_path),
            "worktree_path": str(worktree_path),
            "head": head,
            "checkout_mode": "detached",
        }

    def _codex_prompt(self, packet: dict[str, Any], agent_worktree: dict[str, Any], fran_worktree: dict[str, Any]) -> str:
        payload = {
            "instruction": "Diagnose the crash packet, propose the smallest safe repair, and stop after planning unless explicitly asked to edit.",
            "packet": {
                "job_id": packet.get("job_id", ""),
                "message": packet.get("message", ""),
                "stage": infer_stage(packet),
                "failure_class": classify_failure(packet),
                "stderr_tail": packet.get("stderr_tail", []),
                "stdout_tail": packet.get("stdout_tail", []),
            },
            "repos": {
                "agent": agent_worktree["worktree_path"],
                "fran": fran_worktree["worktree_path"],
            },
        }
        return json.dumps(payload, indent=2, sort_keys=True)
