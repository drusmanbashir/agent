from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from agent.control_plane.fran_adapters import (
    ensure_datasource_local,
    ensure_project_local,
    inspect_datasource_local,
    inspect_project_local,
)
from agent.control_plane.hpc import (
    classify_registry_job,
    dashboard_context,
    submit_datasource,
    submit_preproc,
    submit_project,
    submit_train as submit_hpc_train,
)
from agent.control_plane.local_registry import (
    build_local_job_crash_packet,
    list_local_jobs,
    poll_local_job,
    read_orchestrator_state,
    record_orchestrator_message,
    submit_local_train_retry,
)
from agent.control_plane.models import BLOCKED, FAILED, READY, RUNNING, SUBMITTED, TIMED_OUT, StatusResult
from agent.control_plane.ollama_orchestrator import decide_train_workflow
from fran.run.project.project_status import (
    confirm_plan_status,
    load_project_cfg_with_preprocess_status,
    project_names,
)

PROJECT_STATUS_SH = Path(__file__).resolve().parents[1] / "hpc" / "cli" / "project_status.sh"
LOCAL_PREPROC_PYTHON = Path("/home/ub/mambaforge/envs/dl/bin/python")
LOCAL_PREPROC_BLOCK_SUSPEND = Path("/home/ub/code/fran/fran/run/misc/block_suspend.py")
LOCAL_PREPROC_SCRIPT = Path("/home/ub/code/fran/fran/run/preproc/analyze_resample.py")
LOCAL_PREPROC_LOG_ROOT = Path("/tmp/agent-control-plane-preproc")
LOCAL_PREPROC_CWD = Path("/home/ub/code/agent")
LOCAL_FRAN_CONF = Path("/s/fran_storage/conf")
LOCAL_PYTHONPATH_ROOTS = [
    "/home/ub/code/localiser",
    "/home/ub/code/fran",
    "/home/ub/code/utilz",
    "/home/ub/code/label_analysis",
]


def list_existing_projects() -> list[dict[str, str]]:
    return [{"name": name} for name in project_names(print_stdout=False)]


def project_summary_counts(plans: list[dict[str, object]]) -> dict[str, int]:
    counts = {"green": 0, "yellow": 0, "red": 0}
    for plan in plans:
        preprocessed = plan["preprocessed"]
        if preprocessed == "both":
            counts["green"] += 1
        elif preprocessed == "one":
            counts["yellow"] += 1
        else:
            counts["red"] += 1
    return counts


def parse_project_status_stdout(stdout: str) -> dict[int, dict[str, str]]:
    statuses = {}
    in_table = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("==="):
            in_table = False
            continue
        if not line or line.startswith("all project statuses:") or line.startswith("num_cases:"):
            continue
        if line.startswith("plan_id"):
            in_table = True
            continue
        if not in_table:
            continue
        parts = line.split()
        if not parts[0].isdigit():
            continue
        statuses[int(parts[0])] = {
            "status_source": parts[1],
            "status_plan_ds": parts[2],
        }
    return statuses


def hpc_project_statuses(name: str) -> dict[int, dict[str, str]]:
    result = subprocess.run(
        [str(PROJECT_STATUS_SH), name],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_project_status_stdout(result.stdout)


def patch_dims_value(plan: dict[str, object]) -> str:
    dim0 = plan["patch_dim0"]
    dim1 = plan["patch_dim1"]
    if dim0 is None or dim1 is None:
        return "-"
    return f"{dim0}x{dim1}"


def remapping_value(plan: dict[str, object]) -> object:
    mode = str(plan["mode"])
    if mode == "source":
        return plan["remapping_source"]
    if mode in {"lbd", "rbd"}:
        return plan["remapping_lbd_rbd"]
    if mode == "whole":
        return plan["remapping_whole"]
    return None


def plan_payload(
    plan_id: int,
    plan: dict[str, object],
    preprocessed: str,
    status_source: str,
    status_plan_ds: str,
) -> dict[str, object]:
    return {
        "plan_id": int(plan_id),
        "mode": str(plan["mode"]),
        "patch_dims": patch_dims_value(plan),
        "remapping": remapping_value(plan),
        "preprocessed": preprocessed,
        "status_source": status_source,
        "status_plan_ds": status_plan_ds,
    }


def preproc_project_name(project_name: str) -> str:
    if project_name == "litsmc":
        return "lits"
    return project_name


def get_project_plans(name: str, mode: str = "local") -> dict[str, object]:
    if mode == "hpc":
        proj, cfg = load_project_cfg_with_preprocess_status(name)
        remote_statuses = hpc_project_statuses(name)

        plans = []
        for plan_id in cfg.plans.index:
            cfg.setup(plan_id, verbose=False)
            plan = cfg.configs["plan_train"]
            remote_status = remote_statuses[int(plan_id)]
            source_present = remote_status["status_source"] == "present"
            final_present = remote_status["status_plan_ds"] == "present"
            if source_present and final_present:
                preprocessed = "both"
            elif source_present or final_present:
                preprocessed = "one"
            else:
                preprocessed = "none"
            plans.append(plan_payload(plan_id, plan, preprocessed, remote_status["status_source"], remote_status["status_plan_ds"]))

        return {
            "project": proj.project_title,
            "num_cases": len(proj),
            "plans": plans,
            "summary": project_summary_counts(plans),
        }

    proj, cfg = load_project_cfg_with_preprocess_status(name)

    plans = []
    for plan_id in cfg.plans.index:
        cfg.setup(plan_id, verbose=False)
        plan = cfg.configs["plan_train"]
        detailed_status = confirm_plan_status(cfg.project, plan)
        plans.append(
            plan_payload(
                plan_id,
                plan,
                cfg.plans.loc[plan_id, "preprocessed"],
                "present" if detailed_status["src_fldr_full"] else "missing",
                "present" if detailed_status["final_fldr_full"] else "missing",
            )
        )

    return {
        "project": proj.project_title,
        "num_cases": len(proj),
        "plans": plans,
        "summary": project_summary_counts(plans),
    }


def datasource_ready(
    name: str,
    mode: str = "local",
    ensure: bool = False,
    num_processes: int = 1,
    job_id: str | None = None,
) -> dict:
    if mode == "local":
        result = ensure_datasource_local(name, num_processes) if ensure else inspect_datasource_local(name, num_processes)
        return result.to_dict()
    local_result = inspect_datasource_local(name, num_processes)
    dash = dashboard_context()
    if job_id:
        job_state = classify_registry_job(job_id)
        if job_state["status"] in {SUBMITTED, RUNNING}:
            return StatusResult(
                target="datasource",
                name=name,
                mode="hpc",
                status=job_state["status"],
                message=job_state["message"],
                details={"local_assessment": local_result.to_dict(), "dashboard": dash, "job_state": job_state},
            ).to_dict()
        if job_state["status"] == "completed":
            verified = inspect_datasource_local(name, num_processes)
            verified.mode = "hpc"
            verified.details["dashboard"] = dash
            verified.details["job_state"] = job_state
            return verified.to_dict()
        return StatusResult(
            target="datasource",
            name=name,
            mode="hpc",
            status=FAILED,
            message=job_state["message"],
            details={"local_assessment": local_result.to_dict(), "dashboard": dash, "job_state": job_state},
        ).to_dict()
    if not ensure or local_result.status == "ready":
        local_payload = local_result.to_dict()
        local_payload["dashboard"] = dash
        return local_payload
    if local_result.status == FAILED:
        failed_payload = local_result.to_dict()
        failed_payload["dashboard"] = dash
        return failed_payload
    job = submit_datasource(name=name, num_processes=num_processes)
    return StatusResult(
        target="datasource",
        name=name,
        mode="hpc",
        status=SUBMITTED,
        message="Datasource repair was submitted through the canonical HPC submit+poll path.",
        details={"local_assessment": local_result.to_dict(), "dashboard": dash},
        job=job,
    ).to_dict()


def project_ready(
    title: str,
    mnemonic: str,
    datasources: list[str],
    mode: str = "local",
    ensure: bool = False,
    num_processes: int = 1,
    test: bool = False,
    job_id: str | None = None,
) -> dict:
    if mode == "local":
        result = (
            ensure_project_local(title, mnemonic, datasources, num_processes, test)
            if ensure
            else inspect_project_local(title, mnemonic, datasources, num_processes, test)
        )
        return result.to_dict()
    local_result = inspect_project_local(title, mnemonic, datasources, num_processes, test)
    dash = dashboard_context()
    if job_id:
        job_state = classify_registry_job(job_id)
        if job_state["status"] in {SUBMITTED, RUNNING}:
            return StatusResult(
                target="project",
                name=title,
                mode="hpc",
                status=job_state["status"],
                message=job_state["message"],
                details={"local_assessment": local_result.to_dict(), "dashboard": dash, "job_state": job_state},
            ).to_dict()
        if job_state["status"] == "completed":
            verified = inspect_project_local(title, mnemonic, datasources, num_processes, test)
            verified.mode = "hpc"
            verified.details["dashboard"] = dash
            verified.details["job_state"] = job_state
            return verified.to_dict()
        return StatusResult(
            target="project",
            name=title,
            mode="hpc",
            status=FAILED,
            message=job_state["message"],
            details={"local_assessment": local_result.to_dict(), "dashboard": dash, "job_state": job_state},
        ).to_dict()
    if not ensure or local_result.status == "ready":
        local_payload = local_result.to_dict()
        local_payload["dashboard"] = dash
        return local_payload
    if local_result.status != "repairable":
        blocked_payload = local_result.to_dict()
        blocked_payload["dashboard"] = dash
        return blocked_payload
    job = submit_project(
        title=title,
        mnemonic=mnemonic,
        datasources=datasources,
        num_processes=num_processes,
        test=test,
    )
    return StatusResult(
        target="project",
        name=title,
        mode="hpc",
        status=SUBMITTED,
        message="Project init was submitted through the canonical HPC submit+poll path.",
        details={"local_assessment": local_result.to_dict(), "dashboard": dash},
        job=job,
    ).to_dict()


def local_preproc_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = list(LOCAL_PYTHONPATH_ROOTS)
    if "PYTHONPATH" in env and env["PYTHONPATH"]:
        pythonpath.append(env["PYTHONPATH"])
    env["FRAN_CONF"] = str(LOCAL_FRAN_CONF)
    env["PYTHONPATH"] = ":".join(pythonpath)
    return env


def submit_local_preproc(project_name: str, plan_id: int) -> dict[str, object]:
    LOCAL_PREPROC_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOCAL_PREPROC_LOG_ROOT / f"{project_name}-plan{plan_id}-{timestamp}.log"
    target_project_name = preproc_project_name(project_name)
    command = [
        str(LOCAL_PREPROC_PYTHON),
        str(LOCAL_PREPROC_BLOCK_SUSPEND),
        str(LOCAL_PREPROC_SCRIPT),
        "--",
        "-t",
        target_project_name,
        "-p",
        str(plan_id),
    ]
    with log_file.open("w") as handle:
        handle.write(f"launched_at={datetime.now().isoformat()}\n")
        handle.write(f"command={' '.join(command)}\n")
        handle.flush()
        proc = subprocess.Popen(
            command,
            cwd=LOCAL_PREPROC_CWD,
            env=local_preproc_env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {
        "target": "preproc",
        "name": project_name,
        "mode": "local",
        "status": SUBMITTED,
        "message": f"Local preproc launched for {project_name} plan {plan_id}.",
        "pid": proc.pid,
        "log_file": str(log_file),
        "command": command,
    }


def submit_hpc_preproc(project_name: str, plan_id: int) -> dict[str, object]:
    job = submit_preproc(project_name, plan_id)
    return StatusResult(
        target="preproc",
        name=project_name,
        mode="hpc",
        status=SUBMITTED,
        message="Preproc was submitted through the canonical HPC submit+poll path.",
        details={"plan_id": plan_id, "dashboard": dashboard_context()},
        job=job,
    ).to_dict()


def preproc_ready(project_name: str, plan_id: int, mode: str = "local") -> dict[str, object]:
    if mode == "hpc":
        return submit_hpc_preproc(project_name, plan_id)
    return submit_local_preproc(project_name, plan_id)


def train_retry_local(
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
    provider: str = "ollama",
    model: str = "",
    escalation_target: str = "",
) -> dict[str, object]:
    job = submit_local_train_retry(
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
    return StatusResult(
        target="train",
        name=project_title,
        mode="local",
        status=SUBMITTED,
        message="Local FRAN train retry was submitted into the shared job registry.",
        details={
            "plan": plan,
            "dashboard": dashboard_context(),
            "provider": provider,
            "model": model,
            "escalation_target": escalation_target,
        },
        job=job,
    ).to_dict()


def train_plan_ready(project_title: str, plan: int, mode: str = "local") -> dict[str, object]:
    existing_projects = {project["name"] for project in list_existing_projects()}
    if project_title not in existing_projects:
        return {
            "target": "train",
            "name": project_title,
            "mode": mode,
            "status": BLOCKED,
            "breakpoint": "project",
            "message": f"Project {project_title} is not registered; project readiness is required before train.",
            "details": {"project": project_title, "plan": plan, "dashboard": dashboard_context()},
        }
    project_payload = get_project_plans(project_title, mode)
    plan_payloads = [item for item in project_payload["plans"] if int(item["plan_id"]) == int(plan)]
    plan_payload = plan_payloads[0]
    if plan_payload["preprocessed"] == "both":
        return {
            "target": "train",
            "name": project_title,
            "mode": mode,
            "status": READY,
            "breakpoint": None,
            "message": f"Project {project_title} plan {plan} has source and plan datasets ready.",
            "details": {"project": project_payload, "plan": plan_payload, "dashboard": dashboard_context()},
        }
    return {
        "target": "train",
        "name": project_title,
        "mode": mode,
        "status": BLOCKED,
        "breakpoint": "preproc",
        "message": f"Project {project_title} plan {plan} needs preprocessing before train.",
        "details": {"project": project_payload, "plan": plan_payload, "dashboard": dashboard_context()},
    }


def observe_train_plan_readiness(project_title: str, plan: int, attempts: int = 2, delay_seconds: float = 1.0) -> tuple[dict[str, object], list[dict[str, object]]]:
    observations = []
    readiness = train_plan_ready(project_title=project_title, plan=plan)
    for attempt in range(1, attempts + 1):
        observations.append(
            {
                "attempt": attempt,
                "status": readiness["status"],
                "message": readiness["message"],
            }
        )
        if readiness["status"] == READY:
            return readiness, observations
        if attempt < attempts:
            time.sleep(delay_seconds)
            readiness = train_plan_ready(project_title=project_title, plan=plan)
    return readiness, observations


def orchestrator_train_request(
    project_title: str,
    plan: int,
    mode: str = "local",
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
    provider: str = "ollama",
    model: str = "",
    escalation_target: str = "",
) -> dict[str, object]:
    readiness = train_plan_ready(project_title=project_title, plan=plan, mode=mode)
    decision = decide_train_workflow(
        project_title=project_title,
        plan=plan,
        readiness=readiness,
        provider=provider,
        model=model,
    )
    record_orchestrator_message(message=decision["message"], mode="train_intent")
    observed_readiness = readiness
    observations: list[dict[str, object]] = []

    if decision["action"] == "return_blocked":
        next_action = "project" if readiness.get("breakpoint") == "project" else "review"
        return StatusResult(
            target="train",
            name=project_title,
            mode=mode,
            status=BLOCKED,
            message=readiness["message"],
            details={
                "plan": plan,
                "dashboard": dashboard_context(),
                "readiness": readiness,
                "decision": decision,
            },
            next_action=next_action,
        ).to_dict()

    if decision["action"] == "submit_preproc":
        preproc_job = preproc_ready(project_name=project_title, plan_id=plan, mode=mode)
        observed_readiness, observations = observe_train_plan_readiness(project_title=project_title, plan=plan)
        if observed_readiness["status"] != READY:
            next_action = "poll" if mode == "hpc" else "preproc"
            return StatusResult(
                target="train",
                name=project_title,
                mode=mode,
                status=TIMED_OUT,
                message="Timed out waiting for preprocessing readiness; preproc was submitted and should be polled via returned job details.",
                details={
                    "plan": plan,
                    "dashboard": dashboard_context(),
                    "readiness": observed_readiness,
                    "decision": decision,
                    "observations": observations,
                    "preproc_job": preproc_job,
                },
                next_action=next_action,
            ).to_dict()

    if mode == "hpc":
        if fold is None or learning_rate is None or train_indices is None:
            return StatusResult(
                target="train",
                name=project_title,
                mode=mode,
                status=BLOCKED,
                message="HPC train submission requires fold, learning_rate, and train_indices.",
                details={
                    "plan": plan,
                    "dashboard": dashboard_context(),
                    "readiness": observed_readiness,
                    "decision": decision,
                },
                next_action="request_complete_args",
            ).to_dict()
        job = submit_hpc_train(
            project_title=project_title,
            plan=plan,
            fold=fold,
            learning_rate=learning_rate,
            train_indices=train_indices,
            val_every_n_epochs=val_every_n_epochs,
            run_name=run_name,
            epochs=epochs,
            wandb=wandb,
            bsf=bsf,
        )
        return StatusResult(
            target="train",
            name=project_title,
            mode=mode,
            status=SUBMITTED,
            message="Orchestrator accepted train intent and submitted HPC train.",
            details={
                "plan": plan,
                "dashboard": dashboard_context(),
                "decision": decision,
                "readiness": observed_readiness,
            },
            job=job,
        ).to_dict()

    payload = train_retry_local(
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
    payload["message"] = "Orchestrator accepted train intent and submitted local train."
    payload["details"]["decision"] = decision
    payload["details"]["readiness"] = observed_readiness
    if observations:
        payload["details"]["observations"] = observations
    payload["job_id"] = payload["job"]["job_id"]
    return payload


def local_job_status(job_id: str) -> dict[str, object]:
    payload = poll_local_job(job_id)
    payload["dashboard"] = dashboard_context()
    return payload


def local_job_list(limit: int = 25) -> dict[str, object]:
    jobs = []
    for item in list_local_jobs(limit=limit):
        job_id = str(item["job_id"])
        job = poll_local_job(job_id)
        job_meta = build_local_job_crash_packet(job_id, tail_lines=0).get("job_meta", {})
        jobs.append(
            {
                **item,
                "project": job_meta.get("project_title", ""),
                "plan_id": int(job_meta["plan"]) if job_meta.get("plan") else None,
                "fold": int(job_meta["fold"]) if job_meta.get("fold") else None,
                "run_name": job_meta.get("run_name", ""),
                "stdout_url": f"/api/local-train/jobs/{job_id}/stdout",
                "stderr_url": f"/api/local-train/jobs/{job_id}/stderr",
                "started_at": item["submitted_at"],
                "message": job["message"],
            }
        )
    return {"jobs": jobs, "dashboard": dashboard_context()}


def local_job_crash_packet(job_id: str, tail_lines: int = 200) -> dict[str, object]:
    payload = build_local_job_crash_packet(job_id=job_id, tail_lines=tail_lines)
    payload["dashboard"] = dashboard_context()
    return payload


def local_job_detail(job_id: str) -> dict[str, object]:
    payload = build_local_job_crash_packet(job_id=job_id, tail_lines=200)
    job = payload.get("job", {})
    job_meta = payload.get("job_meta", {})
    detail = {
        "job_id": job_id,
        "status": payload.get("status"),
        "message": payload.get("message"),
        "project": job_meta.get("project_title", ""),
        "plan_id": int(job_meta["plan"]) if job_meta.get("plan") else None,
        "fold": int(job_meta["fold"]) if job_meta.get("fold") else None,
        "run_name": job_meta.get("run_name", ""),
        "submitted_at": job.get("submitted_at"),
        "finished_at": job.get("finished_at"),
        "last_seen_at": job.get("last_polled_at"),
        "job_dir_path": job.get("job_dir"),
        "stdout_path": job.get("stdout"),
        "stderr_path": job.get("stderr"),
        "stdout_url": f"/api/local-train/jobs/{job_id}/stdout",
        "stderr_url": f"/api/local-train/jobs/{job_id}/stderr",
        "worker_log_path": str(Path(job.get("job_dir", "")) / "worker.log") if job.get("job_dir") else "",
        "poll_log_path": str(Path(job.get("job_dir", "")) / "poll.log") if job.get("job_dir") else "",
        "crash_context": "\n".join(payload.get("stderr_tail", [])),
        "note_context": payload.get("note_context", ""),
        "debug_links": [
            {"label": "Crash packet", "url": f"/api/local-train/jobs/{job_id}/crash"},
            {"label": "std.out", "url": f"/api/local-train/jobs/{job_id}/stdout"},
            {"label": "std.err", "url": f"/api/local-train/jobs/{job_id}/stderr"},
        ],
    }
    return detail


def local_orchestrator_status(limit: int = 10) -> dict[str, object]:
    state = read_orchestrator_state()
    jobs = list_local_jobs(limit=limit)
    failed = [job for job in jobs if job["status"] == FAILED]
    active = [job for job in jobs if job["status"] in {SUBMITTED, RUNNING}]
    if failed:
        state["status"] = "failed"
        state["message"] = f"Latest failed local job: {failed[0]['job_id']}"
        state["debug_links"] = [
            {"label": f"Crash {job['job_id']}", "url": f"/api/local-train/jobs/{job['job_id']}/crash"}
            for job in failed[:3]
        ]
    elif active:
        state["status"] = "running"
        state["message"] = f"{len(active)} local job(s) active."
        state["links"] = [
            {"label": f"Job {job['job_id']}", "url": f"/api/local-train/jobs/{job['job_id']}"}
            for job in active[:3]
        ]
    elif jobs:
        state["status"] = "completed"
        state["message"] = f"Last local job settled: {jobs[0]['job_id']}"
    return state


def post_local_orchestrator_message(message: str, mode: str = "message", job_id: str | None = None) -> dict[str, object]:
    state = record_orchestrator_message(message=message, mode=mode, job_id=job_id)
    return {
        "status": state.get("status", "ready"),
        "message": f"Recorded orchestrator {mode}.",
        "updated_at": state.get("updated_at"),
        "job_id": job_id,
    }
