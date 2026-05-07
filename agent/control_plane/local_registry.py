from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from agent.control_plane.models import FAILED, JobInfo, RUNNING, SUBMITTED
from agent.hpc.tools.job_registry import JobRecord, JobRegistry, read_key_value_file

AGENT_REPO_ROOT = Path("/home/ub/code/agent")
FRAN_REPO_ROOT = Path("/home/ub/code/fran")
LOCAL_TRAIN_PYTHON = Path("/home/ub/mambaforge/envs/dl/bin/python")
LOCAL_TRAIN_ENTRYPOINT = Path("/home/ub/code/fran/fran/run/training/train_retry.py")
LOCAL_LOG_ROOT = Path("/s/agent_rw/local_acp_logs")
LOCAL_LOG_ROOT_FALLBACK = Path.home() / ".agent/local_acp_logs"
LOCAL_ORCH_PROVIDER = "ollama"
LOCAL_ORCH_MODEL = ""
LOCAL_ORCH_ESCALATION_TARGET = ""
LOCAL_ORCH_STATE_FILE = "local_orchestrator_state.json"
LOCAL_ORCH_MESSAGES_FILE = "local_orchestrator_messages.jsonl"
LOCAL_PYTHONPATH_ROOTS = [
    "/home/ub/code/agent",
    "/home/ub/code/fran",
    "/home/ub/code/localiser",
    "/home/ub/code/utilz",
    "/home/ub/code/label_analysis",
]
LOCAL_JOB_INPUT_METHOD = "local_train_retry"


def local_job_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"local-{stamp}-{uuid.uuid4().hex[:8]}"


def _preferred_log_root(primary: Path, fallback: Path) -> Path:
    selected = primary.expanduser()
    probe = selected if selected.exists() else selected.parent
    if probe.exists() and os.access(probe, os.W_OK):
        return selected
    return fallback.expanduser()


def logs_root(root: Path | None = None) -> Path:
    if root is not None:
        resolved = root.expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    selected = _preferred_log_root(LOCAL_LOG_ROOT, LOCAL_LOG_ROOT_FALLBACK)
    selected.mkdir(parents=True, exist_ok=True)
    return selected


def job_registry(root: Path | None = None) -> JobRegistry:
    return JobRegistry(root=logs_root(root))


def local_train_env(pythonpath_roots: list[str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    roots = pythonpath_roots or LOCAL_PYTHONPATH_ROOTS
    pythonpath_entries = list(roots)
    if "PYTHONPATH" in env and env["PYTHONPATH"]:
        pythonpath_entries.append(env["PYTHONPATH"])
    env["FRAN_CONF"] = "/s/fran_storage/conf"
    env["PYTHONPATH"] = ":".join(pythonpath_entries)
    return env


def build_train_retry_command(
    *,
    python_bin: str,
    train_script: str,
    project_title: str,
    plan: int,
    devices: str,
    learning_rate: float | None,
    batch_size: int,
    fold: int | None,
    epochs: int,
    compiled: bool,
    profiler: bool,
    wandb: bool,
    run_name: str | None,
    description: str | None,
    cache_rate: float,
    ds_type: str | None,
    val_every_n_epochs: int,
    train_indices: int | None,
    bsf: bool,
    max_retries: int,
    step: int,
    min_bs: int,
) -> list[str]:
    command = [
        python_bin,
        "-u",
        train_script,
        "--project",
        project_title,
        "--plan-num",
        str(plan),
        "--devices",
        devices,
        "--bs",
        str(batch_size),
        "--epochs",
        str(epochs),
        "--compiled",
        str(compiled).lower(),
        "--profiler",
        str(profiler).lower(),
        "--wandb",
        str(wandb).lower(),
        "--cache-rate",
        str(cache_rate),
        "--val-every-n-epochs",
        str(val_every_n_epochs),
        "--bsf",
        str(bsf).lower(),
        "--max-retries",
        str(max_retries),
        "--step",
        str(step),
        "--min-bs",
        str(min_bs),
    ]
    if learning_rate is not None:
        command.extend(["--learning-rate", str(learning_rate)])
    if fold is not None:
        command.extend(["--fold", str(fold)])
    if run_name is not None:
        command.extend(["--run-name", run_name])
    if description is not None:
        command.extend(["--description", description])
    if ds_type is not None:
        command.extend(["--ds-type", ds_type])
    if train_indices is not None:
        command.extend(["--train-indices", str(train_indices)])
    return command


def write_key_value_file(path: Path, payload: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in payload.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def worker_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath_entries = [str(AGENT_REPO_ROOT)]
    if "PYTHONPATH" in env and env["PYTHONPATH"]:
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = ":".join(pythonpath_entries)
    return env


def is_local_job(job: JobRecord) -> bool:
    return job.resolved_input_method == LOCAL_JOB_INPUT_METHOD or job.job_id.startswith("local-")


def local_job_summary(job: JobRecord) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "job_name": job.job_name,
        "status": classify_local_job(job)["status"],
        "state": job.state,
        "exit_code": job.exit_code,
        "submitted_at": job.submitted_at,
        "finished_at": job.finished_at,
        "last_polled_at": job.last_polled_at,
        "job_dir": str(job.job_dir),
        "stdout": str(job.stdout_path),
        "stderr": str(job.stderr_path),
        "log_root": str(job.root),
        "registry_path": str(job.root / "job_registry.tsv"),
    }


def orchestrator_state_path(root: Path | None = None) -> Path:
    return logs_root(root) / LOCAL_ORCH_STATE_FILE


def orchestrator_messages_path(root: Path | None = None) -> Path:
    return logs_root(root) / LOCAL_ORCH_MESSAGES_FILE


def default_orchestrator_state() -> dict[str, object]:
    return {
        "status": "ready",
        "message": "Local ACP ready. provider=ollama",
        "provider": LOCAL_ORCH_PROVIDER,
        "model": LOCAL_ORCH_MODEL,
        "escalation_target": LOCAL_ORCH_ESCALATION_TARGET,
        "log_root": str(logs_root()),
        "updated_at": datetime.now().astimezone().isoformat(),
    }


def read_orchestrator_state(root: Path | None = None) -> dict[str, object]:
    path = orchestrator_state_path(root)
    if not path.exists():
        return default_orchestrator_state()
    return json.loads(path.read_text(encoding="utf-8"))


def write_orchestrator_state(payload: dict[str, object], root: Path | None = None) -> dict[str, object]:
    path = orchestrator_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def record_orchestrator_message(
    message: str,
    mode: str = "message",
    job_id: str | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    registry = job_registry(root)
    timestamp = datetime.now().astimezone().isoformat()
    state = read_orchestrator_state(root)
    msg_payload = {
        "timestamp": timestamp,
        "mode": mode,
        "job_id": "" if job_id is None else job_id,
        "message": message,
    }
    msg_path = orchestrator_messages_path(root)
    msg_path.parent.mkdir(parents=True, exist_ok=True)
    with msg_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(msg_payload, sort_keys=True) + "\n")
    if job_id:
        job = registry.find(job_id)
        if job is not None:
            note_path = job.job_dir / "note.txt"
            with note_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{timestamp}] {message}\n")
    state["message"] = message
    state["updated_at"] = timestamp
    state["last_mode"] = mode
    state["last_job_id"] = "" if job_id is None else job_id
    write_orchestrator_state(state, root=root)
    return state


def _submit_local_train_retry_job(
    *,
    project_title: str,
    plan: int,
    devices: str = "1",
    learning_rate: float | None = None,
    batch_size: int = 4,
    fold: int | None = None,
    epochs: int = 500,
    compiled: bool = False,
    profiler: bool = False,
    wandb: bool = True,
    run_name: str | None = None,
    description: str | None = None,
    cache_rate: float = 0.0,
    ds_type: str | None = None,
    val_every_n_epochs: int = 5,
    train_indices: int | None = None,
    bsf: bool = True,
    max_retries: int = 3,
    step: int = 1,
    min_bs: int = 1,
    provider: str = LOCAL_ORCH_PROVIDER,
    model: str = LOCAL_ORCH_MODEL,
    escalation_target: str = LOCAL_ORCH_ESCALATION_TARGET,
    root: Path | None = None,
    python_bin: Path = LOCAL_TRAIN_PYTHON,
    train_script: Path = LOCAL_TRAIN_ENTRYPOINT,
    run_cwd: Path = FRAN_REPO_ROOT,
    pythonpath_roots: list[str] | None = None,
) -> JobInfo:
    registry = job_registry(root)
    job_id = local_job_id()
    submitted_at = datetime.now().astimezone().isoformat()
    job_name = f"train_{project_title}_p{plan}" if fold is None else f"train_{project_title}_p{plan}_f{fold}"
    job_dir = registry.root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "std.out").touch()
    (job_dir / "std.err").touch()
    command = build_train_retry_command(
        python_bin=str(python_bin),
        train_script=str(train_script),
        project_title=project_title,
        plan=plan,
        devices=devices,
        learning_rate=learning_rate,
        batch_size=batch_size,
        fold=fold,
        epochs=epochs,
        compiled=compiled,
        profiler=profiler,
        wandb=wandb,
        run_name=run_name,
        description=description,
        cache_rate=cache_rate,
        ds_type=ds_type,
        val_every_n_epochs=val_every_n_epochs,
        train_indices=train_indices,
        bsf=bsf,
        max_retries=max_retries,
        step=step,
        min_bs=min_bs,
    )
    submit_argv = shlex.join(command)
    record = JobRecord(
        job_id=job_id,
        submitted_at=submitted_at,
        sbatch_file=str(train_script),
        job_name=job_name,
        remote_script=f"local:{train_script}",
        state="SUBMITTED",
        exit_code="-",
        finished_at="-",
        last_polled_at="-",
        input_method=LOCAL_JOB_INPUT_METHOD,
        submit_argv=submit_argv,
        root=registry.root,
    )
    registry.add(record)
    write_key_value_file(
        job_dir / "job.meta",
        {
            "input_method": LOCAL_JOB_INPUT_METHOD,
            "submit_argv": submit_argv,
            "job_id": job_id,
            "job_name": job_name,
            "submitted_at": submitted_at,
            "project_title": project_title,
            "plan": str(plan),
            "devices": devices,
            "learning_rate": "" if learning_rate is None else str(learning_rate),
            "batch_size": str(batch_size),
            "fold": "" if fold is None else str(fold),
            "epochs": str(epochs),
            "compiled": str(compiled).lower(),
            "profiler": str(profiler).lower(),
            "wandb": str(wandb).lower(),
            "run_name": "" if run_name is None else run_name,
            "description": "" if description is None else description,
            "cache_rate": str(cache_rate),
            "ds_type": "" if ds_type is None else ds_type,
            "val_every_n_epochs": str(val_every_n_epochs),
            "train_indices": "" if train_indices is None else str(train_indices),
            "bsf": str(bsf).lower(),
            "max_retries": str(max_retries),
            "step": str(step),
            "min_bs": str(min_bs),
            "python_bin": str(python_bin),
            "train_script": str(train_script),
            "run_cwd": str(run_cwd),
            "pythonpath_roots": json.dumps(pythonpath_roots or LOCAL_PYTHONPATH_ROOTS),
            "stdout_path": str(job_dir / "std.out"),
            "stderr_path": str(job_dir / "std.err"),
            "worker_pid_file": str(job_dir / "worker.pid"),
            "worker_meta_file": str(job_dir / "worker.meta"),
        },
    )
    (job_dir / "worker.pid").write_text("", encoding="utf-8")
    (job_dir / "worker.log").touch()
    write_key_value_file(
        job_dir / "worker.meta",
        {
            "job_id": job_id,
            "worker_state": "submitted",
            "submitted_at": submitted_at,
            "stdout_path": str(job_dir / "std.out"),
            "stderr_path": str(job_dir / "std.err"),
            "job_meta": str(job_dir / "job.meta"),
            "worker_pid_file": str(job_dir / "worker.pid"),
            "worker_log": str(job_dir / "worker.log"),
        },
    )
    orch_payload = {
        "provider": provider,
        "model": model,
        "escalation_target": escalation_target,
        "job_id": job_id,
        "job_name": job_name,
        "submitted_at": submitted_at,
        "entrypoint": str(train_script),
    }
    (job_dir / "orch.json").write_text(json.dumps(orch_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_orchestrator_state(
        {
            "status": "running",
            "message": f"Submitted local train job {job_id}.",
            "provider": provider,
            "model": model,
            "escalation_target": escalation_target,
            "updated_at": submitted_at,
            "last_job_id": job_id,
        },
        root=registry.root,
    )
    worker_command = [
        sys.executable,
        "-m",
        "agent.control_plane.local_job_worker",
        "--job-id",
        job_id,
        "--root",
        str(registry.root),
    ]
    with (job_dir / "worker.log").open("a", encoding="utf-8") as worker_log:
        proc = subprocess.Popen(
            worker_command,
            cwd=str(AGENT_REPO_ROOT),
            env=worker_launch_env(),
            stdout=worker_log,
            stderr=worker_log,
            start_new_session=True,
        )
    (job_dir / "worker.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    write_key_value_file(
        job_dir / "worker.meta",
        {
            "job_id": job_id,
            "worker_pid": str(proc.pid),
            "worker_state": "spawned",
            "submitted_at": submitted_at,
            "stdout_path": str(job_dir / "std.out"),
            "stderr_path": str(job_dir / "std.err"),
            "job_meta": str(job_dir / "job.meta"),
            "worker_pid_file": str(job_dir / "worker.pid"),
            "worker_log": str(job_dir / "worker.log"),
        },
    )
    return JobInfo(
        job_id=job_id,
        command=command,
        job_dir=str(job_dir),
        state=SUBMITTED,
        dashboard_url=None,
    )


def submit_local_train_retry(
    *,
    project_title: str,
    plan: int,
    devices: str = "1",
    learning_rate: float | None = None,
    batch_size: int = 4,
    fold: int | None = None,
    epochs: int = 500,
    compiled: bool = False,
    profiler: bool = False,
    wandb: bool = True,
    run_name: str | None = None,
    description: str | None = None,
    cache_rate: float = 0.0,
    ds_type: str | None = None,
    val_every_n_epochs: int = 5,
    train_indices: int | None = None,
    bsf: bool = True,
    max_retries: int = 3,
    step: int = 1,
    min_bs: int = 1,
    provider: str = LOCAL_ORCH_PROVIDER,
    model: str = LOCAL_ORCH_MODEL,
    escalation_target: str = LOCAL_ORCH_ESCALATION_TARGET,
) -> JobInfo:
    return _submit_local_train_retry_job(
        project_title=project_title,
        plan=plan,
        devices=devices,
        learning_rate=learning_rate,
        batch_size=batch_size,
        fold=fold,
        epochs=epochs,
        compiled=compiled,
        profiler=profiler,
        wandb=wandb,
        run_name=run_name,
        description=description,
        cache_rate=cache_rate,
        ds_type=ds_type,
        val_every_n_epochs=val_every_n_epochs,
        train_indices=train_indices,
        bsf=bsf,
        max_retries=max_retries,
        step=step,
        min_bs=min_bs,
        provider=provider,
        model=model,
        escalation_target=escalation_target,
    )


def _pid_is_live(pid: str) -> bool:
    return pid.isdigit() and Path(f"/proc/{pid}").exists()


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()[-limit:]


def _sync_local_job(job: JobRecord) -> JobRecord:
    registry = job_registry(job.root)
    worker_meta = read_key_value_file(job.worker_meta_path)
    if "final_state" in worker_meta and "final_exit" in worker_meta and "finished_at" in worker_meta:
        if job.finished_at != worker_meta["finished_at"] or job.state != worker_meta["final_state"]:
            updated = registry.update_status(
                job.job_id,
                worker_meta["final_state"],
                worker_meta["final_exit"],
                worker_meta["finished_at"],
            )
            registry.update_polled(job.job_id, datetime.now().astimezone().isoformat())
            return updated
    if job.state in {"SUBMITTED", "RUNNING"} and "worker_pid" in worker_meta:
        if _pid_is_live(worker_meta["worker_pid"]):
            state = "RUNNING" if worker_meta["worker_state"] in {"running", "completed"} else "SUBMITTED"
            updated = registry.update_status(job.job_id, state, job.exit_code, job.finished_at)
            registry.update_polled(job.job_id, datetime.now().astimezone().isoformat())
            return updated
        finished_at = datetime.now().astimezone().isoformat()
        updated = registry.update_status(job.job_id, "FAILED", job.exit_code, finished_at)
        write_key_value_file(
            job.worker_meta_path,
            {
                **worker_meta,
                "worker_state": "failed",
                "final_state": "FAILED",
                "final_exit": job.exit_code,
                "finished_at": finished_at,
            },
        )
        registry.update_polled(job.job_id, finished_at)
        return updated
    return job


def classify_local_job(job: JobRecord) -> dict[str, object]:
    if job.state in {"", "-", "SUBMITTED"}:
        return {"job_id": job.job_id, "status": SUBMITTED, "message": "Job is submitted and waiting for the local worker."}
    if job.state == "RUNNING":
        return {"job_id": job.job_id, "status": RUNNING, "message": "Job is running locally."}
    if job.state == "COMPLETED" and job.exit_code in {"", "-", "0", "0:0"}:
        return {"job_id": job.job_id, "status": "completed", "message": "Job completed successfully."}
    return {
        "job_id": job.job_id,
        "status": FAILED,
        "message": f"Job finished in state {job.state or '-'} with exit {job.exit_code or '-'}.",
    }


def poll_local_job(job_id: str, root: Path | None = None) -> dict[str, object]:
    registry = job_registry(root)
    job = registry.find(job_id)
    if job is None:
        return {
            "job_id": job_id,
            "status": FAILED,
            "message": f"Job {job_id} was not found in {registry.path}.",
            "log_root": str(registry.root),
            "registry_path": str(registry.path),
        }
    synced = _sync_local_job(job)
    registry.update_polled(job_id, datetime.now().astimezone().isoformat())
    refreshed = registry.find(job_id)
    status = classify_local_job(refreshed)
    status["job"] = local_job_summary(refreshed)
    status["log_root"] = str(registry.root)
    status["registry_path"] = str(registry.path)
    return status


def list_local_jobs(limit: int = 25, root: Path | None = None) -> list[dict[str, object]]:
    registry = job_registry(root)
    jobs = [job for job in registry.load() if is_local_job(job)]
    jobs.sort(key=lambda job: (job.submitted_at, job.job_id), reverse=True)
    return [local_job_summary(_sync_local_job(job)) for job in jobs[:limit]]


def build_local_job_crash_packet(job_id: str, tail_lines: int = 200, root: Path | None = None) -> dict[str, object]:
    registry = job_registry(root)
    job = registry.find(job_id)
    if job is None:
        return {
            "job_id": job_id,
            "status": FAILED,
            "message": f"Job {job_id} was not found in {registry.path}.",
            "log_root": str(registry.root),
            "registry_path": str(registry.path),
        }
    refreshed = _sync_local_job(job)
    status = classify_local_job(refreshed)
    job_meta = read_key_value_file(refreshed.job_meta_path)
    worker_meta = read_key_value_file(refreshed.worker_meta_path)
    orch = json.loads(refreshed.orch_path.read_text(encoding="utf-8")) if refreshed.orch_path.exists() else {}
    note_path = refreshed.job_dir / "note.txt"
    return {
        "job_id": refreshed.job_id,
        "status": status["status"],
        "message": status["message"],
        "job": local_job_summary(refreshed),
        "job_meta": job_meta,
        "worker_meta": worker_meta,
        "orchestrator": orch,
        "log_root": str(refreshed.root),
        "registry_path": str(registry.path),
        "stdout_tail": _tail_lines(refreshed.stdout_path, tail_lines),
        "stderr_tail": _tail_lines(refreshed.stderr_path, tail_lines),
        "note_context": note_path.read_text(encoding="utf-8") if note_path.exists() else "",
    }
