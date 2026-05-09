from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agent.control_plane.hpc import dashboard_context
from agent.control_plane.models import JobInfo, StatusResult
from agent.control_plane.schemas import TrainRequest
from agent.control_plane.service import (
    datasource_ready,
    get_project_plans,
    local_job_crash_packet,
    local_job_detail,
    local_job_list,
    local_orchestrator_status,
    list_existing_projects,
    orchestrator_train_request,
    preproc_ready,
    project_ready,
    post_local_orchestrator_message,
)

app = FastAPI(title="Agent Control Plane")
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def parse_datasources(value: str) -> list[str]:
    cleaned = value.replace("\n", ",")
    parts = [part.strip() for part in cleaned.split(",")]
    return [part for part in parts if part]


def base_context(request: Request) -> dict:
    return {
        "request": request,
        "dashboard": dashboard_context(),
        "projects": list_existing_projects(),
        "active_tab": "projects",
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
        "datasource_form": {
            "name": "",
            "mode": "local",
            "ensure": False,
            "num_processes": 1,
            "job_id": "",
        },
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


def acp_context(request: Request) -> dict:
    return {
        "request": request,
        "main_dashboard_url": "/",
        "acp_api": {
            "status": "/api/acp/status",
            "jobs": "/api/acp/jobs",
            "job_detail_prefix": "/api/acp/jobs",
            "message": "/api/acp/messages",
        },
    }


def train_status_result(payload: dict[str, object]) -> dict[str, object]:
    details = {}
    if "details" in payload and payload["details"] is not None:
        details = dict(payload["details"])
    if "decision" in payload:
        details["decision"] = payload["decision"]
    if "breakpoint" in payload and payload["breakpoint"] is not None:
        details["breakpoint"] = payload["breakpoint"]

    job = None
    if "job" in payload and payload["job"] is not None:
        job_payload = payload["job"]
        job = JobInfo(
            job_id=str(job_payload["job_id"]),
            command=list(job_payload["command"]),
            job_dir=job_payload["job_dir"],
            state=job_payload["state"],
            dashboard_url=job_payload["dashboard_url"],
        )

    next_action = None
    if "next_action" in payload and payload["next_action"] is not None:
        next_action = str(payload["next_action"])
    elif "breakpoint" in payload and payload["breakpoint"] is not None:
        next_action = str(payload["breakpoint"])

    result = StatusResult(
        target=str(payload["target"]),
        name=str(payload["name"]),
        mode=str(payload["mode"]),
        status=str(payload["status"]),
        message=str(payload["message"]),
        details=details,
        job=job,
        error_code=str(payload["error_code"]) if "error_code" in payload and payload["error_code"] is not None else None,
        next_action=next_action,
        observed_at=str(payload["observed_at"]) if "observed_at" in payload and payload["observed_at"] is not None else None,
    )
    return result.to_dict()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    context = await run_in_threadpool(base_context, request)
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/acp", response_class=HTMLResponse)
async def acp_index(request: Request):
    context = await run_in_threadpool(acp_context, request)
    return templates.TemplateResponse(request, "acp.html", context)


@app.get("/api/projects")
async def projects_api():
    projects = await run_in_threadpool(list_existing_projects)
    return {"projects": projects}


@app.get("/api/projects/{project_name}")
async def project_detail_api(project_name: str, mode: str = "local"):
    try:
        return await run_in_threadpool(get_project_plans, project_name, mode)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects")
async def create_project_api(
    title: str = Body(...),
    mnemonic: str = Body(...),
    datasources: str = Body(""),
    mode: str = Body("local"),
    num_processes: int = Body(1),
    test: bool = Body(False),
):
    return await run_in_threadpool(
        project_ready,
        title=title,
        mnemonic=mnemonic,
        datasources=parse_datasources(datasources),
        mode=mode,
        ensure=True,
        num_processes=num_processes,
        test=test,
        job_id=None,
    )


@app.post("/api/projects/{project_name}/plans/{plan_id}/preproc")
async def project_preproc_api(
    project_name: str,
    plan_id: int,
    mode: str = Body(..., embed=True),
):
    try:
        return await run_in_threadpool(preproc_ready, project_name, plan_id, mode)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/orchestrator/requests/train")
@app.post("/api/acp/requests/train")
async def orchestrator_train_request_api(request: TrainRequest):
    payload = await run_in_threadpool(orchestrator_train_request, **request.service_kwargs())
    return train_status_result(payload)


@app.get("/api/local-train/jobs")
@app.get("/api/acp/jobs")
async def local_train_jobs_api(limit: int = 25):
    return await run_in_threadpool(local_job_list, limit)


@app.get("/api/local-train/jobs/{job_id}")
@app.get("/api/acp/jobs/{job_id}")
async def local_train_job_detail_api(job_id: str):
    return await run_in_threadpool(local_job_detail, job_id)


@app.get("/api/local-train/jobs/{job_id}/crash")
@app.get("/api/acp/jobs/{job_id}/crash")
async def local_train_job_crash_api(job_id: str, tail_lines: int = 200):
    return await run_in_threadpool(local_job_crash_packet, job_id, tail_lines)


@app.get("/api/local-train/jobs/{job_id}/stdout")
@app.get("/api/acp/jobs/{job_id}/stdout")
async def local_train_job_stdout_api(job_id: str):
    payload = await run_in_threadpool(local_job_detail, job_id)
    stdout_path = payload.get("stdout_path")
    if not stdout_path or not Path(stdout_path).exists():
        raise HTTPException(status_code=404, detail=f"stdout missing for {job_id}")
    return FileResponse(stdout_path, media_type="text/plain", filename=f"{job_id}-std.out")


@app.get("/api/local-train/jobs/{job_id}/stderr")
@app.get("/api/acp/jobs/{job_id}/stderr")
async def local_train_job_stderr_api(job_id: str):
    payload = await run_in_threadpool(local_job_detail, job_id)
    stderr_path = payload.get("stderr_path")
    if not stderr_path or not Path(stderr_path).exists():
        raise HTTPException(status_code=404, detail=f"stderr missing for {job_id}")
    return FileResponse(stderr_path, media_type="text/plain", filename=f"{job_id}-std.err")


@app.get("/api/local-train/orchestrator")
@app.get("/api/acp/status")
async def local_orchestrator_api():
    return await run_in_threadpool(local_orchestrator_status)


@app.post("/api/local-train/orchestrator/messages")
@app.post("/api/acp/messages")
async def local_orchestrator_message_api(
    message: str = Body(...),
    mode: str = Body("message"),
    job_id: str | None = Body(None),
):
    return await run_in_threadpool(post_local_orchestrator_message, message, mode, job_id)


@app.post("/datasource/ready", response_class=HTMLResponse)
async def datasource_ready_view(
    request: Request,
    name: str = Form(...),
    mode: str = Form("local"),
    ensure: bool = Form(False),
    num_processes: int = Form(1),
    job_id: str = Form(""),
):
    context = await run_in_threadpool(base_context, request)
    context["active_tab"] = "datasources"
    context["datasource_form"] = {
        "name": name,
        "mode": mode,
        "ensure": ensure,
        "num_processes": num_processes,
        "job_id": job_id,
    }
    context["datasource_result"] = await run_in_threadpool(
        datasource_ready,
        name=name,
        mode=mode,
        ensure=ensure,
        num_processes=num_processes,
        job_id=job_id or None,
    )
    return templates.TemplateResponse(request, "index.html", context)


@app.post("/project/ready", response_class=HTMLResponse)
async def project_ready_view(
    request: Request,
    title: str = Form(...),
    mnemonic: str = Form(...),
    datasources: str = Form(""),
    mode: str = Form("local"),
    ensure: bool = Form(False),
    num_processes: int = Form(1),
    test: bool = Form(False),
    job_id: str = Form(""),
):
    context = await run_in_threadpool(base_context, request)
    parsed_datasources = parse_datasources(datasources)
    context["active_tab"] = "new-project"
    context["project_form"] = {
        "title": title,
        "mnemonic": mnemonic,
        "datasources": datasources,
        "mode": mode,
        "ensure": ensure,
        "num_processes": num_processes,
        "test": test,
        "job_id": job_id,
    }
    context["project_result"] = await run_in_threadpool(
        project_ready,
        title=title,
        mnemonic=mnemonic,
        datasources=parsed_datasources,
        mode=mode,
        ensure=ensure,
        num_processes=num_processes,
        test=test,
        job_id=job_id or None,
    )
    return templates.TemplateResponse(request, "index.html", context)
