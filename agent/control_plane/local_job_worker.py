from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from agent.control_plane.local_registry import build_train_retry_command, job_registry, local_train_env, write_key_value_file
from agent.hpc.tools.job_registry import read_key_value_file


def _meta_str(meta: dict[str, str], key: str) -> str | None:
    value = meta[key].strip()
    return value or None


def _meta_int(meta: dict[str, str], key: str) -> int | None:
    value = meta[key].strip()
    return int(value) if value else None


def _meta_float(meta: dict[str, str], key: str) -> float | None:
    value = meta[key].strip()
    return float(value) if value else None


def _meta_bool(meta: dict[str, str], key: str) -> bool:
    return meta[key].strip().lower() in {"1", "true", "t", "yes", "y"}


def run_local_job(job_id: str, root: Path | None = None) -> int:
    registry = job_registry(root)
    job = registry.find(job_id)
    job_meta = read_key_value_file(job.job_meta_path)
    started_at = datetime.now().astimezone().isoformat()
    write_key_value_file(
        job.worker_meta_path,
        {
            "job_id": job.job_id,
            "worker_pid": str(os.getpid()),
            "worker_state": "running",
            "started_at": started_at,
            "stdout_path": str(job.stdout_path),
            "stderr_path": str(job.stderr_path),
            "job_meta": str(job.job_meta_path),
            "worker_pid_file": str(job.job_dir / "worker.pid"),
            "worker_log": str(job.worker_log_path),
        },
    )
    registry.update_status(job.job_id, "RUNNING", "-", "-")
    registry.update_polled(job.job_id, started_at)
    command = build_train_retry_command(
        python_bin=job_meta["python_bin"],
        train_script=job_meta["train_script"],
        project_title=job_meta["project_title"],
        plan=int(job_meta["plan"]),
        devices=job_meta["devices"],
        learning_rate=_meta_float(job_meta, "learning_rate"),
        batch_size=int(job_meta["batch_size"]),
        fold=_meta_int(job_meta, "fold"),
        epochs=int(job_meta["epochs"]),
        compiled=_meta_bool(job_meta, "compiled"),
        profiler=_meta_bool(job_meta, "profiler"),
        wandb=_meta_bool(job_meta, "wandb"),
        run_name=_meta_str(job_meta, "run_name"),
        description=_meta_str(job_meta, "description"),
        cache_rate=float(job_meta["cache_rate"]),
        ds_type=_meta_str(job_meta, "ds_type"),
        val_every_n_epochs=int(job_meta["val_every_n_epochs"]),
        train_indices=_meta_int(job_meta, "train_indices"),
        bsf=_meta_bool(job_meta, "bsf"),
        max_retries=int(job_meta["max_retries"]),
        step=int(job_meta["step"]),
        min_bs=int(job_meta["min_bs"]),
    )
    env = local_train_env(json.loads(job_meta["pythonpath_roots"]))
    with job.stdout_path.open("a", encoding="utf-8") as stdout_handle:
        with job.stderr_path.open("a", encoding="utf-8") as stderr_handle:
            proc = subprocess.Popen(
                command,
                cwd=job_meta["run_cwd"],
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
            )
            (job.job_dir / "worker.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
            write_key_value_file(
                job.worker_meta_path,
                {
                    "job_id": job.job_id,
                    "worker_pid": str(proc.pid),
                    "worker_state": "running",
                    "started_at": started_at,
                    "stdout_path": str(job.stdout_path),
                    "stderr_path": str(job.stderr_path),
                    "job_meta": str(job.job_meta_path),
                    "worker_pid_file": str(job.job_dir / "worker.pid"),
                    "worker_log": str(job.worker_log_path),
                },
            )
            rc = proc.wait()
    finished_at = datetime.now().astimezone().isoformat()
    final_state = "COMPLETED" if rc == 0 else "FAILED"
    registry.update_status(job.job_id, final_state, str(rc), finished_at)
    registry.update_polled(job.job_id, finished_at)
    write_key_value_file(
        job.worker_meta_path,
        {
            "job_id": job.job_id,
            "worker_pid": str(proc.pid),
            "worker_state": "completed" if rc == 0 else "failed",
            "started_at": started_at,
            "finished_at": finished_at,
            "final_state": final_state,
            "final_exit": str(rc),
            "stdout_path": str(job.stdout_path),
            "stderr_path": str(job.stderr_path),
            "job_meta": str(job.job_meta_path),
            "worker_pid_file": str(job.job_dir / "worker.pid"),
            "worker_log": str(job.worker_log_path),
        },
    )
    return rc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a detached local FRAN train job and persist registry state.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--root", default="")
    args = parser.parse_args()
    root = Path(args.root).expanduser() if args.root else None
    raise SystemExit(run_local_job(args.job_id, root))


if __name__ == "__main__":
    main()
