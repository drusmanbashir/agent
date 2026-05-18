#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import uvicorn
import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.job_registry import JobRecord, JobRegistry, read_key_value_file

POLL_SCRIPT = REPO_ROOT / "cli" / "hpc_poll_logs.sh"
RESUBMIT_SCRIPT = REPO_ROOT / "cli" / "hpc_resubmit.sh"
REFRESH_SCRIPT = REPO_ROOT / "cli" / "refresh.sh"
SSH_SCRIPT = REPO_ROOT / "cli" / "hpc_ssh.sh"
TEMPLATE_DIR = Path(__file__).with_name("templates") / "hpc_dashboard"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_LIMIT = "30"
DEFAULT_SCOPE = "hpc"
LIMIT_OPTIONS = ("30", "50", "100", "all")
SOURCE_SCOPES = ("hpc", "local")
SORT_COLUMNS = ("job_id", "state", "job_name", "submitted_at", "last_polled_at", "exit_code", "finished_at")


def now_text() -> str:
    return time.strftime("%d/%m/%Y %H:%M:%S")


def cold_storage_from_env() -> str:
    fran_conf = os.environ["FRAN_CONF"]
    config_path = Path(fran_conf) / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config["cold_storage_folder"]


def action_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["COLD_STORAGE"] = cold_storage_from_env()
    return env


@dataclass(slots=True)
class PageState:
    selected: str
    tab: str
    sort: str
    direction: str
    limit: str
    scope: str

    def params(self, message: str = "") -> dict[str, str]:
        params = {
            "selected": self.selected,
            "tab": self.tab,
            "sort": self.sort,
            "direction": self.direction,
            "limit": self.limit,
            "scope": self.scope,
        }
        if message:
            params["message"] = message
        return params


@dataclass(slots=True)
class ActionSnapshot:
    running: bool
    label: str
    detail: str
    started_at: str
    finished_at: str


@dataclass(slots=True)
class ActionRunner:
    state_dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    running: bool = False
    label: str = "idle"
    detail: str = "No background actions yet."
    started_at: str = "-"
    finished_at: str = "-"

    @property
    def log_path(self) -> Path:
        return self.state_dir / "actions.log"

    def snapshot(self) -> ActionSnapshot:
        with self.lock:
            return ActionSnapshot(self.running, self.label, self.detail, self.started_at, self.finished_at)

    def _claim(self, label: str, detail: str) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.label = label
            self.detail = detail
            self.started_at = now_text()
            self.finished_at = "-"
            return True

    def _finish(self, detail: str) -> None:
        with self.lock:
            self.running = False
            self.detail = detail
            self.finished_at = now_text()

    def start_command(self, label: str, command: list[str]) -> str:
        if not self._claim(label, " ".join(command)):
            return f"Action already running: {self.label}"

        def worker() -> None:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{now_text()}] start {label}: {' '.join(command)}\n")
                handle.flush()
                result = subprocess.run(
                    command,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=action_subprocess_env(),
                )
                summary = f"rc={result.returncode}"
                handle.write(f"[{now_text()}] done {label}: {summary}\n")
                handle.flush()
            self._finish(summary)

        threading.Thread(target=worker, daemon=True).start()
        return f"Started {label}."

    def start_job_batch(self, label: str, commands: list[list[str]]) -> str:
        if not self._claim(label, "queued"):
            return f"Action already running: {self.label}"

        def worker() -> None:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            parts: list[str] = []
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{now_text()}] start {label}\n")
                handle.flush()
                for command in commands:
                    handle.write(f"[{now_text()}] run {' '.join(command)}\n")
                    handle.flush()
                    result = subprocess.run(
                        command,
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=action_subprocess_env(),
                    )
                    parts.append(f"{command[-1]}:{result.returncode}")
                summary = " ".join(parts) if parts else "no jobs"
                handle.write(f"[{now_text()}] done {label}: {summary}\n")
                handle.flush()
            self._finish(summary)

        threading.Thread(target=worker, daemon=True).start()
        return f"Started {label}."


@dataclass(slots=True)
class DashboardRuntime:
    registry: JobRegistry
    actions: ActionRunner
    templates: Jinja2Templates
    poll_script: Path
    poll_env: dict[str, str] | None = None


def normalize_tab(tab: str) -> str:
    if tab == "closed":
        return "closed"
    return "active"


def default_sort_key(tab: str) -> str:
    if tab == "closed":
        return "finished_at"
    return "submitted_at"


def normalize_sort(sort: str, tab: str) -> str:
    if sort in SORT_COLUMNS:
        return sort
    return default_sort_key(tab)


def normalize_direction(direction: str) -> str:
    if direction == "asc":
        return "asc"
    return "desc"


def normalize_limit(limit: str) -> str:
    if limit in LIMIT_OPTIONS:
        return limit
    return DEFAULT_LIMIT


def normalize_scope(scope: str) -> str:
    if scope in SOURCE_SCOPES:
        return scope
    return DEFAULT_SCOPE


def build_view(selected: str, tab: str, sort: str, direction: str, limit: str, scope: str) -> PageState:
    tab = normalize_tab(tab)
    return PageState(
        selected=selected,
        tab=tab,
        sort=normalize_sort(sort, tab),
        direction=normalize_direction(direction),
        limit=normalize_limit(limit),
        scope=normalize_scope(scope),
    )


def is_local_job(job: JobRecord) -> bool:
    return job.resolved_input_method == "local_train_retry" or job.job_id.startswith("local-")


def source_scope_for_job(job: JobRecord) -> str:
    if is_local_job(job):
        return "local"
    return "hpc"


def jobs_for_scope(jobs: list[JobRecord], scope: str) -> list[JobRecord]:
    return [job for job in jobs if source_scope_for_job(job) == scope]


def limit_jobs(jobs: list[JobRecord], limit: str) -> list[JobRecord]:
    if limit == "all":
        return jobs
    return jobs[: int(limit)]


def sort_value(job: JobRecord, sort: str) -> tuple[int, str]:
    if sort == "job_id":
        value = job.job_id
    elif sort == "state":
        value = job.state
    elif sort == "job_name":
        value = job.job_name
    elif sort == "submitted_at":
        value = job.submitted_at
    elif sort == "last_polled_at":
        value = job.last_polled_at
    elif sort == "exit_code":
        value = job.exit_code
    else:
        value = job.finished_at
    return (1 if value in {"", "-"} else 0, value)


def sort_jobs(jobs: list[JobRecord], sort: str, direction: str) -> list[JobRecord]:
    return sorted(jobs, key=lambda job: sort_value(job, sort), reverse=direction == "desc")


def action_output(log_path: Path, label: str) -> str:
    if label == "idle" or not log_path.exists():
        return ""
    lines = log_path.read_text(encoding="utf-8").splitlines()
    marker = f"start {label}"
    start = 0
    for index, line in enumerate(lines):
        if marker in line:
            start = index
    return "\n".join(lines[start:]).strip()


def summary_pairs(job: JobRecord) -> list[tuple[str, str]]:
    return [
        ("job_id", job.job_id),
        ("state", job.state),
        ("job_name", job.job_name),
        ("submitted_at", job.display_submitted_at),
        ("last_polled_at", job.display_last_polled_at),
        ("finished_at", job.display_finished_at),
        ("exit_code", job.exit_code),
        ("sbatch_file", job.sbatch_file),
        ("remote_script", job.remote_script),
        ("job_dir", str(job.job_dir)),
    ]


def metadata_pairs(path: Path) -> list[tuple[str, str]]:
    return list(read_key_value_file(path).items())


def alternate_local_log_paths(job: JobRecord, asset: str) -> list[Path]:
    if not job.job_dir.exists():
        return []
    if asset == "stdout":
        suffix = ".out"
        canonical_name = "std.out"
    else:
        suffix = ".err"
        canonical_name = "std.err"
    return sorted(
        path for path in job.job_dir.iterdir()
        if path.is_file() and path.name != canonical_name and path.name.endswith(suffix)
    )


def run_poll_job(job_id: str, poll_script: Path, env: dict[str, str] | None = None) -> int:
    result = subprocess.run(
        [str(poll_script), job_id],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=action_subprocess_env() if env is None else env,
    )
    return result.returncode


def run_poll_jobs(job_ids: list[str], poll_script: Path, env: dict[str, str] | None = None) -> str:
    if not job_ids:
        return "No jobs to poll."
    failures = [job_id for job_id in job_ids if run_poll_job(job_id, poll_script, env) != 0]
    if failures:
        return f"Poll failed: {', '.join(failures)}"
    if len(job_ids) == 1:
        return f"Polled {job_ids[0]}."
    return f"Polled {len(job_ids)} jobs."


def build_app(state_dir: Path, registry_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="HPC Jobs Dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    runtime = DashboardRuntime(JobRegistry(registry_root), ActionRunner(state_dir), templates, POLL_SCRIPT)
    app.state.dashboard = runtime

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok\n")

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        selected: str = "",
        tab: str = "active",
        sort: str = "",
        direction: str = "desc",
        limit: str = DEFAULT_LIMIT,
        scope: str = DEFAULT_SCOPE,
        message: str = "",
    ) -> HTMLResponse:
        view = build_view(selected, tab, sort, direction, limit, scope)
        active_jobs, closed_jobs = runtime.registry.split_jobs()
        active_jobs = sort_jobs(jobs_for_scope(active_jobs, view.scope), view.sort, view.direction)
        closed_jobs = sort_jobs(jobs_for_scope(closed_jobs, view.scope), view.sort, view.direction)
        visible_jobs = limit_jobs(active_jobs if view.tab == "active" else closed_jobs, view.limit)
        selected_job = runtime.registry.find(view.selected) if view.selected else None
        if selected_job is not None and source_scope_for_job(selected_job) != view.scope:
            selected_job = None
        snapshot = runtime.actions.snapshot()
        context = {
            "request": request,
            "urlencode": urlencode,
            "view": view,
            "message": message,
            "active_jobs": active_jobs,
            "closed_jobs": closed_jobs,
            "jobs": visible_jobs,
            "selected_job": selected_job,
            "summary_pairs": [] if selected_job is None else summary_pairs(selected_job),
            "job_meta_pairs": [] if selected_job is None else metadata_pairs(selected_job.job_meta_path),
            "worker_meta_pairs": [] if selected_job is None else metadata_pairs(selected_job.worker_meta_path),
            "activity": snapshot,
            "activity_output": action_output(runtime.actions.log_path, snapshot.label),
            "limit_options": LIMIT_OPTIONS,
            "registry_path": runtime.registry.path,
        }
        return runtime.templates.TemplateResponse(request, "index.html", context)

    @app.post("/actions/global/poll-all-active")
    def poll_all_active(
        selected: str = Form(""),
        tab: str = Form("active"),
        sort: str = Form(""),
        direction: str = Form("desc"),
        limit: str = Form(DEFAULT_LIMIT),
        scope: str = Form(DEFAULT_SCOPE),
    ) -> RedirectResponse:
        view = build_view(selected, tab, sort, direction, limit, scope)
        active_jobs = jobs_for_scope(runtime.registry.active_jobs(), view.scope)
        message = run_poll_jobs([job.job_id for job in active_jobs], runtime.poll_script, runtime.poll_env)
        return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)

    @app.post("/actions/global/refresh-hpc")
    def refresh_hpc(
        selected: str = Form(""),
        tab: str = Form("active"),
        sort: str = Form(""),
        direction: str = Form("desc"),
        limit: str = Form(DEFAULT_LIMIT),
        scope: str = Form(DEFAULT_SCOPE),
    ) -> RedirectResponse:
        view = build_view(selected, tab, sort, direction, limit, scope)
        message = runtime.actions.start_command("refresh hpc state", [str(REFRESH_SCRIPT), "--yes"])
        return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)

    @app.post("/actions/job/{job_id}/poll")
    def poll_job(
        job_id: str,
        selected: str = Form(""),
        tab: str = Form("active"),
        sort: str = Form(""),
        direction: str = Form("desc"),
        limit: str = Form(DEFAULT_LIMIT),
        scope: str = Form(DEFAULT_SCOPE),
    ) -> RedirectResponse:
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
        limit: str = Form(DEFAULT_LIMIT),
        scope: str = Form(DEFAULT_SCOPE),
    ) -> RedirectResponse:
        view = build_view(selected or job_id, tab, sort, direction, limit, scope)
        commands = [
            [str(SSH_SCRIPT), f"/opt/slurm/bin/scancel {job_id}"],
            [str(POLL_SCRIPT), job_id],
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
        limit: str = Form(DEFAULT_LIMIT),
        scope: str = Form(DEFAULT_SCOPE),
    ) -> RedirectResponse:
        view = build_view(selected or job_id, tab, sort, direction, limit, scope)
        message = runtime.actions.start_job_batch("resubmit job", [[str(RESUBMIT_SCRIPT), job_id]])
        return RedirectResponse(f"/?{urlencode(view.params(message))}", status_code=303)

    @app.get("/jobs/{job_id}/{asset}", response_model=None)
    def job_asset(request: Request, job_id: str, asset: str, scope: str = DEFAULT_SCOPE):
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
            "job": job,
            "asset": asset,
            "path": str(path),
            "scope": scope,
            "raw_paths": alternate_local_log_paths(job, asset),
        }
        return runtime.templates.TemplateResponse(request, "missing_asset.html", context, status_code=404)

    return app


def write_meta(path: Path, host: str, port: int, state_dir: Path, registry: JobRegistry) -> str:
    url = f"http://{host}:{port}/"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"pid={os.getpid()}",
                f"host={host}",
                f"port={port}",
                f"url={url}",
                f"started_at={now_text()}",
                f"state_dir={state_dir}",
                f"registry={registry.path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return url


def main(args: argparse.Namespace) -> int:
    app = build_app(args.state_dir)
    write_meta(args.meta_file, args.host, args.port, args.state_dir, app.state.dashboard.registry)
    print(f"http://{args.host}:{args.port}/", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FastAPI dashboard for HPC job registry.")
    parser.add_argument("--host", default=os.environ.get("HPC_DASHBOARD_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HPC_DASHBOARD_PORT", DEFAULT_PORT)))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--meta-file", type=Path, required=True)
    args = parser.parse_known_args()[0]
    raise SystemExit(main(args))
