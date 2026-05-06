from __future__ import annotations

from pathlib import Path

from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agent.control_plane.hpc import dashboard_context
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    context = await run_in_threadpool(base_context, request)
    return templates.TemplateResponse(request, "index.html", context)


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
async def orchestrator_train_request_api(
    project: str = Body(...),
    plan_id: int = Body(...),
    fold: int = Body(0),
    train_indices: int = Body(24),
    val_every_n_epochs: int = Body(5),
    learning_rate: str = Body("0.0003"),
    run_name: str = Body("none"),
):
    return await run_in_threadpool(
        orchestrator_train_request,
        project_title=project,
        plan=plan_id,
        fold=fold,
        train_indices=train_indices,
        val_every_n_epochs=val_every_n_epochs,
        learning_rate=float(learning_rate),
        run_name=None if run_name in {"", "none", "null"} else run_name,
    )


@app.get("/api/local-train/jobs")
async def local_train_jobs_api(limit: int = 25):
    return await run_in_threadpool(local_job_list, limit)


@app.get("/api/local-train/jobs/{job_id}")
async def local_train_job_detail_api(job_id: str):
    return await run_in_threadpool(local_job_detail, job_id)


@app.get("/api/local-train/jobs/{job_id}/crash")
async def local_train_job_crash_api(job_id: str, tail_lines: int = 200):
    return await run_in_threadpool(local_job_crash_packet, job_id, tail_lines)


@app.get("/api/local-train/jobs/{job_id}/stdout")
async def local_train_job_stdout_api(job_id: str):
    payload = await run_in_threadpool(local_job_detail, job_id)
    stdout_path = payload.get("stdout_path")
    if not stdout_path or not Path(stdout_path).exists():
        raise HTTPException(status_code=404, detail=f"stdout missing for {job_id}")
    return FileResponse(stdout_path, media_type="text/plain", filename=f"{job_id}-std.out")


@app.get("/api/local-train/jobs/{job_id}/stderr")
async def local_train_job_stderr_api(job_id: str):
    payload = await run_in_threadpool(local_job_detail, job_id)
    stderr_path = payload.get("stderr_path")
    if not stderr_path or not Path(stderr_path).exists():
        raise HTTPException(status_code=404, detail=f"stderr missing for {job_id}")
    return FileResponse(stderr_path, media_type="text/plain", filename=f"{job_id}-std.err")


@app.get("/api/local-train/orchestrator")
async def local_orchestrator_api():
    return await run_in_threadpool(local_orchestrator_status)


@app.post("/api/local-train/orchestrator/messages")
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
