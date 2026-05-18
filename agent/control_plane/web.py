from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agent.control_plane.models import JobInfo, StatusResult
from agent.control_plane.schemas import TrainRequest
from agent.control_plane.service import (
    delete_project,
    datasource_ready,
    get_project_plans,
    list_existing_projects,
    local_job_crash_packet,
    local_job_detail,
    local_job_list,
    local_orchestrator_status,
    ollama_prompt,
    orchestrator_train_request,
    post_local_orchestrator_message,
    preproc_ready,
    project_ready,
)
from agent.hpc.cli.hpc_dashboard_web import (
    ActionRunner,
    DashboardRuntime,
    JobRegistry,
    action_output,
    alternate_local_log_paths,
    build_view,
    jobs_for_scope,
    limit_jobs,
    metadata_pairs,
    POLL_SCRIPT,
    run_poll_jobs,
    sort_jobs,
    source_scope_for_job,
    summary_pairs,
)
from agent.storage_roots import storage_root

app = FastAPI(title="FRAN Site")
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
jobs_runtime: DashboardRuntime | None = None


def parse_datasources(value: str) -> list[str]:
    cleaned = value.replace("\n", ",")
    parts = [part.strip() for part in cleaned.split(",")]
    return [part for part in parts if part]


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


def get_jobs_runtime() -> DashboardRuntime:
    global jobs_runtime
    if jobs_runtime is None:
        state_dir = storage_root("hpc_logs") / "dashboard_state"
        jobs_runtime = DashboardRuntime(JobRegistry(), ActionRunner(state_dir), templates, POLL_SCRIPT)
    return jobs_runtime


def jobs_page_context(
    request: Request,
    selected: str = "",
    tab: str = "active",
    sort: str = "",
    direction: str = "desc",
    limit: str = "30",
    scope: str = "hpc",
    message: str = "",
) -> dict[str, object]:
    runtime = get_jobs_runtime()
    view = build_view(selected, tab, sort, direction, limit, scope)
    active_jobs, closed_jobs = runtime.registry.split_jobs()
    active_jobs = sort_jobs(jobs_for_scope(active_jobs, view.scope), view.sort, view.direction)
    closed_jobs = sort_jobs(jobs_for_scope(closed_jobs, view.scope), view.sort, view.direction)
    jobs = limit_jobs(active_jobs if view.tab == "active" else closed_jobs, view.limit)
    selected_job = runtime.registry.find(view.selected) if view.selected else None
    if selected_job is not None and source_scope_for_job(selected_job) != view.scope:
        selected_job = None
    activity = runtime.actions.snapshot()
    return {
        "request": request,
        "title": "Jobs",
        "nav_page": "jobs",
        "message": message,
        "view": view,
        "jobs": jobs,
        "active_jobs": active_jobs,
        "closed_jobs": closed_jobs,
        "selected_job": selected_job,
        "summary_pairs": [] if selected_job is None else summary_pairs(selected_job),
        "job_meta_pairs": [] if selected_job is None else metadata_pairs(selected_job.job_meta_path),
        "worker_meta_pairs": [] if selected_job is None else metadata_pairs(selected_job.worker_meta_path),
        "activity": activity,
        "activity_output": action_output(runtime.actions.log_path, activity.label),
        "limit_options": ("30", "50", "100", "all"),
        "registry_path": runtime.registry.path,
    }


def projects_defaults() -> dict[str, object]:
    return {
        "project_name": "",
        "project_mode": "local",
        "project_payload": None,
        "command_output": "",
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
        "datasource_form": {
            "name": "",
            "mode": "local",
            "ensure": False,
            "num_processes": 1,
            "job_id": "",
        },
        "ollama_form": {
            "model": "llama3.1",
            "prompt": "",
        },
        "project_result": None,
        "datasource_result": None,
        "preproc_result": None,
        "ollama_result": None,
    }


def payload_command_output(payload: dict[str, object] | None) -> str:
    if not payload:
        return ""
    if payload.get("command_stdout"):
        return str(payload["command_stdout"])
    details = payload.get("details")
    if isinstance(details, dict) and details.get("command_stdout"):
        return str(details["command_stdout"])
    return ""


def projects_page_context(
    request: Request,
    project_name: str = "",
    project_mode: str = "local",
    message: str = "",
    defaults: dict[str, object] | None = None,
) -> dict[str, object]:
    context = projects_defaults() if defaults is None else defaults
    if project_name:
        project_payload = get_project_plans(project_name, project_mode)
        context["project_payload"] = project_payload
        if not context.get("command_output"):
            context["command_output"] = payload_command_output(project_payload)
    context["request"] = request
    context["title"] = "Projects"
    context["nav_page"] = "projects"
    context["message"] = message
    context["projects"] = list_existing_projects()
    context["project_name"] = project_name
    context["project_mode"] = project_mode
    return context


def training_page_context(request: Request) -> dict[str, object]:
    return {
        "request": request,
        "title": "Training",
        "nav_page": "training",
    }


@app.get("/health")
def health() -> PlainTextResponse:
    return PlainTextResponse("ok\n")


@app.get("/healthz")
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok\n")


@app.get("/", response_class=HTMLResponse)
def jobs_home(
    request: Request,
    selected: str = "",
    tab: str = "active",
    sort: str = "",
    direction: str = "desc",
    limit: str = "30",
    scope: str = "hpc",
    message: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(request, "jobs.html", jobs_page_context(request, selected, tab, sort, direction, limit, scope, message))


@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, project: str = "", mode: str = "local", message: str = "") -> HTMLResponse:
    return templates.TemplateResponse(request, "projects.html", projects_page_context(request, project, mode, message))


@app.get("/training", response_class=HTMLResponse)
@app.get("/train", response_class=HTMLResponse)
def training_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "training.html", training_page_context(request))


@app.post("/actions/global/poll-all-active")
def poll_all_active(
    selected: str = Form(""),
    tab: str = Form("active"),
    sort: str = Form(""),
    direction: str = Form("desc"),
    limit: str = Form("30"),
    scope: str = Form("hpc"),
) -> RedirectResponse:
    runtime = get_jobs_runtime()
    view = build_view(selected, tab, sort, direction, limit, scope)
    message = run_poll_jobs([job.job_id for job in jobs_for_scope(runtime.registry.active_jobs(), view.scope)], runtime.poll_script, runtime.poll_env)
    return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)


@app.post("/actions/global/refresh-hpc")
def refresh_hpc(
    selected: str = Form(""),
    tab: str = Form("active"),
    sort: str = Form(""),
    direction: str = Form("desc"),
    limit: str = Form("30"),
    scope: str = Form("hpc"),
) -> RedirectResponse:
    runtime = get_jobs_runtime()
    view = build_view(selected, tab, sort, direction, limit, scope)
    script = Path(__file__).resolve().parents[1] / "hpc" / "cli" / "refresh.sh"
    message = runtime.actions.start_command("refresh hpc state", [str(script), "--yes"])
    return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)


@app.post("/actions/job/{job_id}/poll")
def poll_job(
    job_id: str,
    selected: str = Form(""),
    tab: str = Form("active"),
    sort: str = Form(""),
    direction: str = Form("desc"),
    limit: str = Form("30"),
    scope: str = Form("hpc"),
) -> RedirectResponse:
    runtime = get_jobs_runtime()
    view = build_view(selected or job_id, tab, sort, direction, limit, scope)
    message = run_poll_jobs([job_id], runtime.poll_script, runtime.poll_env)
    return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)


@app.post("/actions/job/{job_id}/cancel")
def cancel_job(
    job_id: str,
    selected: str = Form(""),
    tab: str = Form("active"),
    sort: str = Form(""),
    direction: str = Form("desc"),
    limit: str = Form("30"),
    scope: str = Form("hpc"),
) -> RedirectResponse:
    runtime = get_jobs_runtime()
    view = build_view(selected or job_id, tab, sort, direction, limit, scope)
    ssh_script = Path(__file__).resolve().parents[1] / "hpc" / "cli" / "hpc_ssh.sh"
    poll_script = Path(__file__).resolve().parents[1] / "hpc" / "cli" / "hpc_poll_logs.sh"
    commands = [
        [str(ssh_script), f"/opt/slurm/bin/scancel {job_id}"],
        [str(poll_script), job_id],
    ]
    message = runtime.actions.start_job_batch("cancel job", commands)
    return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)


@app.post("/actions/job/{job_id}/resubmit")
def resubmit_job(
    job_id: str,
    selected: str = Form(""),
    tab: str = Form("active"),
    sort: str = Form(""),
    direction: str = Form("desc"),
    limit: str = Form("30"),
    scope: str = Form("hpc"),
) -> RedirectResponse:
    runtime = get_jobs_runtime()
    view = build_view(selected or job_id, tab, sort, direction, limit, scope)
    script = Path(__file__).resolve().parents[1] / "hpc" / "cli" / "hpc_resubmit.sh"
    message = runtime.actions.start_job_batch("resubmit job", [[str(script), job_id]])
    return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)


@app.get("/jobs/{job_id}/{asset}", response_model=None)
def jobs_asset(request: Request, job_id: str, asset: str, scope: str = "hpc"):
    runtime = get_jobs_runtime()
    job = runtime.registry.find(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    if asset == "stdout":
        path = job.stdout_path
    elif asset == "stderr":
        path = job.stderr_path
    elif asset == "poll-log":
        path = job.poll_log_path
    else:
        raise HTTPException(status_code=404, detail=f"Unknown asset {asset}")
    if path.exists():
        return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))
    context = {
        "request": request,
        "title": "Missing Asset",
        "nav_page": "jobs",
        "job": job,
        "asset": asset,
        "path": str(path),
        "scope": scope,
        "raw_paths": alternate_local_log_paths(job, asset),
    }
    return templates.TemplateResponse(request, "missing_asset.html", context, status_code=404)


@app.post("/projects/inspect", response_class=HTMLResponse)
def projects_inspect(request: Request, project: str = Form(""), mode: str = Form("local")) -> HTMLResponse:
    return templates.TemplateResponse(request, "projects.html", projects_page_context(request, project, mode))


@app.post("/projects/delete", response_class=HTMLResponse)
def projects_delete(request: Request, project: str = Form(""), mode: str = Form("local")) -> HTMLResponse:
    defaults = projects_defaults()
    if not project:
        defaults["command_output"] = "No project selected."
        return templates.TemplateResponse(
            request,
            "projects.html",
            projects_page_context(request, "", mode, "Select project before delete.", defaults),
        )
    result = delete_project(project)
    defaults["command_output"] = payload_command_output(result)
    deleted = result.get("status") == "completed"
    message = f"Deleted project {project}." if deleted else result.get("message", f"Project {project} delete failed.")
    selected_project = "" if deleted else project
    return templates.TemplateResponse(
        request,
        "projects.html",
        projects_page_context(request, selected_project, mode, message, defaults),
    )


@app.post("/projects/preproc", response_class=HTMLResponse)
def projects_preproc(
    request: Request,
    project_name: str = Form(...),
    plan_id: int = Form(...),
    mode: str = Form("local"),
) -> HTMLResponse:
    defaults = projects_defaults()
    defaults["preproc_result"] = preproc_ready(project_name, plan_id, mode)
    defaults["command_output"] = payload_command_output(defaults["preproc_result"])
    return templates.TemplateResponse(
        request,
        "projects.html",
        projects_page_context(request, project_name, mode, f"Preproc submitted for {project_name} plan {plan_id}.", defaults),
    )


@app.post("/projects/ollama", response_class=HTMLResponse)
def projects_ollama(request: Request, model: str = Form("llama3.1"), prompt: str = Form(...)) -> HTMLResponse:
    defaults = projects_defaults()
    defaults["ollama_form"] = {"model": model, "prompt": prompt}
    defaults["ollama_result"] = ollama_prompt(prompt=prompt, model=model)
    defaults["command_output"] = payload_command_output(defaults["ollama_result"])
    return templates.TemplateResponse(request, "projects.html", projects_page_context(request, "", "local", "Ollama request completed.", defaults))


@app.post("/datasource/ready", response_class=HTMLResponse)
def datasource_ready_view(
    request: Request,
    name: str = Form(...),
    mode: str = Form("local"),
    ensure: bool = Form(False),
    num_processes: int = Form(1),
    job_id: str = Form(""),
) -> HTMLResponse:
    defaults = projects_defaults()
    defaults["datasource_form"] = {
        "name": name,
        "mode": mode,
        "ensure": ensure,
        "num_processes": num_processes,
        "job_id": job_id,
    }
    defaults["datasource_result"] = datasource_ready(name, mode, ensure, num_processes, job_id or None)
    defaults["command_output"] = payload_command_output(defaults["datasource_result"])
    return templates.TemplateResponse(request, "projects.html", projects_page_context(request, "", mode, "Datasource check complete.", defaults))


@app.post("/project/ready", response_class=HTMLResponse)
def project_ready_view(
    request: Request,
    title: str = Form(...),
    mnemonic: str = Form(...),
    datasources: str = Form(""),
    mode: str = Form("local"),
    ensure: bool = Form(False),
    num_processes: int = Form(1),
    test: bool = Form(False),
    job_id: str = Form(""),
) -> HTMLResponse:
    defaults = projects_defaults()
    defaults["project_form"] = {
        "title": title,
        "mnemonic": mnemonic,
        "datasources": datasources,
        "mode": mode,
        "ensure": ensure,
        "num_processes": num_processes,
        "test": test,
        "job_id": job_id,
    }
    defaults["project_result"] = project_ready(title, mnemonic, parse_datasources(datasources), mode, ensure, num_processes, test, job_id or None)
    defaults["command_output"] = payload_command_output(defaults["project_result"])
    return templates.TemplateResponse(request, "projects.html", projects_page_context(request, "", mode, "Project check complete.", defaults))


@app.get("/api/projects")
def projects_api():
    return {"projects": list_existing_projects()}


@app.get("/api/projects/{project_name}")
def project_detail_api(project_name: str, mode: str = "local"):
    return get_project_plans(project_name, mode)


@app.post("/api/projects")
def create_project_api(
    title: str = Body(...),
    mnemonic: str = Body(...),
    datasources: str = Body(""),
    mode: str = Body("local"),
    num_processes: int = Body(1),
    test: bool = Body(False),
):
    return project_ready(title, mnemonic, parse_datasources(datasources), mode, True, num_processes, test, None)


@app.post("/api/projects/{project_name}/plans/{plan_id}/preproc")
def project_preproc_api(project_name: str, plan_id: int, mode: str = Body(..., embed=True)):
    return preproc_ready(project_name, plan_id, mode)


@app.post("/api/ollama/prompt")
def ollama_prompt_api(prompt: str = Body(...), model: str = Body("llama3.1")):
    return ollama_prompt(prompt=prompt, model=model)


@app.post("/api/orchestrator/requests/train")
@app.post("/api/acp/requests/train")
def orchestrator_train_request_api(request: TrainRequest):
    return train_status_result(orchestrator_train_request(**request.service_kwargs()))


@app.get("/api/local-train/jobs")
@app.get("/api/acp/jobs")
def local_train_jobs_api(limit: int = 25):
    return local_job_list(limit)


@app.get("/api/local-train/jobs/{job_id}")
@app.get("/api/acp/jobs/{job_id}")
def local_train_job_detail_api(job_id: str):
    return local_job_detail(job_id)


@app.get("/api/local-train/jobs/{job_id}/crash")
@app.get("/api/acp/jobs/{job_id}/crash")
def local_train_job_crash_api(job_id: str, tail_lines: int = 200):
    return local_job_crash_packet(job_id, tail_lines)


@app.get("/api/local-train/jobs/{job_id}/stdout")
@app.get("/api/acp/jobs/{job_id}/stdout")
def local_train_job_stdout_api(job_id: str):
    payload = local_job_detail(job_id)
    stdout_path = payload["stdout_path"]
    if not Path(stdout_path).exists():
        raise HTTPException(status_code=404, detail=f"stdout missing for {job_id}")
    return FileResponse(stdout_path, media_type="text/plain", filename=f"{job_id}-std.out")


@app.get("/api/local-train/jobs/{job_id}/stderr")
@app.get("/api/acp/jobs/{job_id}/stderr")
def local_train_job_stderr_api(job_id: str):
    payload = local_job_detail(job_id)
    stderr_path = payload["stderr_path"]
    if not Path(stderr_path).exists():
        raise HTTPException(status_code=404, detail=f"stderr missing for {job_id}")
    return FileResponse(stderr_path, media_type="text/plain", filename=f"{job_id}-std.err")


@app.get("/api/local-train/orchestrator")
@app.get("/api/acp/status")
def local_orchestrator_api():
    return local_orchestrator_status()


@app.post("/api/local-train/orchestrator/messages")
@app.post("/api/acp/messages")
def local_orchestrator_message_api(
    message: str = Body(...),
    mode: str = Body("message"),
    job_id: str | None = Body(None),
):
    return post_local_orchestrator_message(message, mode, job_id)
