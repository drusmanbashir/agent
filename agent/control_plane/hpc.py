from __future__ import annotations

import csv
import os
import re
import subprocess
from pathlib import Path

from agent.control_plane.models import FAILED, JobInfo, RUNNING, SUBMITTED
from fran.data.dataregistry import DS

HPC_SUBMIT = Path("/home/ub/code/agent/agent/hpc/cli/hpc_submit_poll_fetch.sh")
HPC_DATASOURCE_WRAPPER = Path("/home/ub/code/agent/agent/hpc/cli/datasource.sh")
HPC_PREPROC_WRAPPER = Path("/home/ub/code/agent/agent/hpc/cli/preproc.sh")
HPC_PROJECT_WRAPPER = Path("/home/ub/code/agent/agent/hpc/cli/project_init.sh")
HPC_TRAIN_WRAPPER = Path("/home/ub/code/agent/agent/hpc/cli/train.sh")
HPC_DASH = Path("/home/ub/code/agent/agent/hpc/cli/hdash")
HPC_REGISTRY = Path("/s/agent_rw/hpc_logs/job_registry.tsv")
FRAN_JOBS_PAGE_URL = "http://127.0.0.1:8000/hpc/jobs"


def hpc_log_root() -> Path:
    return HPC_REGISTRY.parent


def fran_jobs_page_url() -> str:
    url = os.environ.get("FRAN_JOBS_PAGE_URL", FRAN_JOBS_PAGE_URL).strip()
    return url or FRAN_JOBS_PAGE_URL


def dashboard_context() -> dict[str, str | None]:
    url = fran_jobs_page_url()
    return {
        "message": "FRAN webapp jobs page is the canonical status surface for submitted HPC jobs.",
        "start_command": f"python -m webbrowser {url}",
        "status_command": f"open {url} to inspect job status in the FRAN webapp",
        "url_command": f"echo {url}",
        "url": url,
        "log_root": str(hpc_log_root()),
    }


def _submit(command: list[str]) -> JobInfo:
    proc = subprocess.run(command, capture_output=True, text=True, check=True)
    output = proc.stdout
    job_id = re.search(r"Submitted batch job (\d+)", output)[1]
    job_dir_match = re.search(r"job_dir=(.+)", output)
    job_dir = job_dir_match[1].strip() if job_dir_match else None
    dash = dashboard_context()
    return JobInfo(
        job_id=job_id,
        command=command,
        job_dir=job_dir,
        state=SUBMITTED,
        dashboard_url=dash["url"],
    )


def submit_datasource(name: str, num_processes: int = 1) -> JobInfo:
    spec = DS[name]
    command = [
        str(HPC_SUBMIT),
        str(HPC_DATASOURCE_WRAPPER),
        str(Path(spec.folder).expanduser().resolve()),
        spec.ds,
        "-n",
        str(num_processes),
    ]
    return _submit(command)


def submit_project(
    title: str,
    mnemonic: str,
    datasources: list[str],
    num_processes: int = 1,
    test: bool = False,
) -> JobInfo:
    command = [
        str(HPC_SUBMIT),
        str(HPC_PROJECT_WRAPPER),
        title,
        mnemonic,
        *datasources,
        "-n",
        str(num_processes),
    ]
    if test:
        command.append("--test")
    return _submit(command)


def submit_preproc(project_name: str, plan_id: int) -> JobInfo:
    command = [
        str(HPC_SUBMIT),
        str(HPC_PREPROC_WRAPPER),
        project_name,
        str(plan_id),
    ]
    return _submit(command)


def submit_train(
    project_title: str,
    plan: int,
    fold: int,
    learning_rate: float,
    train_indices: int,
    val_every_n_epochs: int,
    run_name: str | None,
    epochs: int = 500,
    wandb: bool = True,
    bsf: bool = True,
) -> JobInfo:
    command = [
        str(HPC_SUBMIT),
        str(HPC_TRAIN_WRAPPER),
        project_title,
        str(plan),
        str(fold),
        str(learning_rate),
        str(train_indices),
        str(val_every_n_epochs),
        run_name or "none",
        f"epochs={epochs}",
        f"wandb={str(wandb).lower()}",
        f"bsf={str(bsf).lower()}",
    ]
    return _submit(command)


def registry_row(job_id: str) -> dict[str, str] | None:
    if not HPC_REGISTRY.exists():
        return None
    with HPC_REGISTRY.open() as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if not row or row[0] != job_id:
                continue
            cells = row + [""] * (9 - len(row))
            return {
                "job_id": cells[0],
                "submitted_at": cells[1],
                "sbatch_file": cells[2],
                "job_name": cells[3],
                "remote_script": cells[4],
                "state": cells[5],
                "exit_code": cells[6],
                "finished_at": cells[7],
                "last_polled_at": cells[8],
            }
    return None


def classify_registry_job(job_id: str) -> dict[str, str]:
    row = registry_row(job_id)
    if row is None:
        return {
            "job_id": job_id,
            "status": FAILED,
            "message": f"Job {job_id} was not found in {HPC_REGISTRY}.",
            "log_root": str(hpc_log_root()),
        }
    raw_state = row["state"].strip()
    if raw_state in {"", "-", "PENDING", "PD", "CONFIGURING", "CF"}:
        return {"job_id": job_id, "status": SUBMITTED, "message": "Job is submitted and waiting.", "log_root": str(hpc_log_root())}
    if raw_state in {"RUNNING", "R", "COMPLETING", "CG"}:
        return {"job_id": job_id, "status": RUNNING, "message": "Job is running.", "log_root": str(hpc_log_root())}
    if raw_state in {"COMPLETED", "CD"} and row["exit_code"] in {"", "0", "0:0"}:
        return {"job_id": job_id, "status": "completed", "message": "Job completed successfully.", "log_root": str(hpc_log_root())}
    return {
        "job_id": job_id,
        "status": FAILED,
        "message": f"Job finished in state {raw_state or '-'} with exit {row['exit_code'] or '-'}.",
        "log_root": str(hpc_log_root()),
    }
