#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.job_registry import JobRecord, JobRegistry, read_key_value_file

POLL_SCRIPT = REPO_ROOT / "cli" / "hpc_poll_logs.sh"
RESUBMIT_SCRIPT = REPO_ROOT / "cli" / "hpc_resubmit.sh"
SSH_SCRIPT = REPO_ROOT / "cli" / "hpc_ssh.sh"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SORT_COLUMNS = ("job_id", "state", "job_name", "submitted_at", "last_polled_at", "exit_code", "finished_at")
LIMIT_OPTIONS = ("30", "50", "100", "all")
DEFAULT_LIMIT = "30"
SOURCE_SCOPES = ("hpc", "local")
DEFAULT_SOURCE_SCOPE = "hpc"


def now_text() -> str:
    return time.strftime("%d/%m/%Y %H:%M:%S")


def action_subprocess_env(logs_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    root = str(logs_root)
    env["HPC_LOGS_LOCAL_ROOT"] = root
    env["HPC_POLL_LOG_DEST"] = root
    return env


@dataclass(slots=True)
class ActionState:
    state_dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    running: bool = False
    label: str = "idle"
    detail: str = "No poll actions yet."
    started_at: str = "-"
    finished_at: str = "-"

    @property
    def log_path(self) -> Path:
        return self.state_dir / "actions.log"

    def snapshot(self) -> dict[str, str]:
        with self.lock:
            return {
                "running": "yes" if self.running else "no",
                "label": self.label,
                "detail": self.detail,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def start(self, label: str, detail: str) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.label = label
            self.detail = detail
            self.started_at = now_text()
            self.finished_at = "-"
            return True

    def finish(self, detail: str) -> None:
        with self.lock:
            self.running = False
            self.detail = detail
            self.finished_at = now_text()


class DashboardHandler(BaseHTTPRequestHandler):
    registry: JobRegistry
    action_state: ActionState
    state_dir: Path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            params = parse_qs(parsed.query)
            selected_job_id = params["selected"][0] if "selected" in params else ""
            active_tab = params["tab"][0] if "tab" in params else "active"
            sort_key = params["sort"][0] if "sort" in params else default_sort_key(active_tab)
            sort_dir = params["dir"][0] if "dir" in params else "desc"
            limit = params["limit"][0] if "limit" in params else DEFAULT_LIMIT
            scope = params["scope"][0] if "scope" in params else DEFAULT_SOURCE_SCOPE
            self._send_html(self._render_index(selected_job_id, active_tab, sort_key, sort_dir, limit, scope))
            return
        if parsed.path == "/healthz":
            self._send_text("ok\n")
            return
        if parsed.path.startswith("/jobs/"):
            self._serve_job_asset(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        form = self._read_form()
        selected_job_id = form["job_id"][0] if "job_id" in form else ""
        active_tab = form["tab"][0] if "tab" in form else "active"
        sort_key = form["sort"][0] if "sort" in form else default_sort_key(active_tab)
        sort_dir = form["dir"][0] if "dir" in form else "desc"
        limit = form["limit"][0] if "limit" in form else DEFAULT_LIMIT
        scope = form["scope"][0] if "scope" in form else DEFAULT_SOURCE_SCOPE
        if parsed.path == "/poll_selected":
            self._handle_poll_selected(selected_job_id, active_tab, sort_key, sort_dir, limit, scope)
            return
        if parsed.path == "/poll_all_active":
            self._handle_poll_all_active(active_tab, sort_key, sort_dir, limit, scope)
            return
        if parsed.path == "/cancel_selected":
            self._handle_cancel_selected(selected_job_id, active_tab, sort_key, sort_dir, limit, scope)
            return
        if parsed.path == "/resubmit_selected":
            self._handle_resubmit_selected(selected_job_id, active_tab, sort_key, sort_dir, limit, scope)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_form(self) -> dict[str, list[str]]:
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size).decode("utf-8")
        return parse_qs(body, keep_blank_values=True)

    def _handle_poll_selected(self, selected_job_id: str, active_tab: str, sort_key: str, sort_dir: str, limit: str, scope: str) -> None:
        if not selected_job_id:
            self._redirect("/", {"selected": "", "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": "Select a job first."})
            return
        job = self.registry.find(selected_job_id)
        if job is None:
            self._redirect("/", {"tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": f"Job {selected_job_id} is no longer in the registry."})
            return
        message = self._start_poll_thread([job.job_id], f"poll selected {job.job_id}")
        self._redirect("/", {"selected": job.job_id, "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": message})

    def _handle_poll_all_active(self, active_tab: str, sort_key: str, sort_dir: str, limit: str, scope: str) -> None:
        jobs = jobs_for_scope(self.registry.active_jobs(), scope)
        if not jobs:
            self._redirect("/", {"tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": "No active jobs to poll."})
            return
        job_ids = [job.job_id for job in jobs]
        message = self._start_job_action_thread(job_ids, f"poll all active ({len(job_ids)})", POLL_SCRIPT)
        self._redirect("/", {"tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": message})

    def _handle_cancel_selected(self, selected_job_id: str, active_tab: str, sort_key: str, sort_dir: str, limit: str, scope: str) -> None:
        if active_tab != "active":
            self._redirect("/", {"selected": selected_job_id, "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": "Cancel Selected is available only on Active Jobs."})
            return
        if not selected_job_id:
            self._redirect("/", {"selected": "", "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": "Select an active job first."})
            return
        job = self.registry.find(selected_job_id)
        if job is None:
            self._redirect("/", {"tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": f"Job {selected_job_id} is no longer in the registry."})
            return
        if job.closed:
            self._redirect("/", {"selected": job.job_id, "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": f"Job {job.job_id} is closed and cannot be cancelled."})
            return
        message = self._start_cancel_thread(job)
        self._redirect("/", {"selected": job.job_id, "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": message})

    def _handle_resubmit_selected(self, selected_job_id: str, active_tab: str, sort_key: str, sort_dir: str, limit: str, scope: str) -> None:
        if not selected_job_id:
            self._redirect("/", {"selected": "", "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": "Select a job first."})
            return
        job = self.registry.find(selected_job_id)
        if job is None:
            self._redirect("/", {"tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": f"Job {selected_job_id} is no longer in the registry."})
            return
        if not job.has_submit_provenance:
            self._redirect(
                "/",
                {
                    "selected": job.job_id,
                    "tab": active_tab,
                    "sort": sort_key,
                    "dir": sort_dir,
                    "limit": limit,
                    "scope": scope,
                    "message": f"Job {job.job_id} has no resubmit provenance in the registry.",
                },
            )
            return
        message = self._start_job_action_thread([job.job_id], f"resubmit selected {job.job_id}", RESUBMIT_SCRIPT)
        self._redirect("/", {"selected": job.job_id, "tab": active_tab, "sort": sort_key, "dir": sort_dir, "limit": limit, "scope": scope, "message": message})

    def _start_job_action_thread(self, job_ids: list[str], label: str, script_path: Path) -> str:
        detail = " ".join(job_ids)
        if not self.action_state.start(label, detail):
            snapshot = self.action_state.snapshot()
            return f"Action already running: {snapshot['label']}"

        def run_jobs() -> None:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.action_state.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{now_text()}] start {label}: {detail}\n")
                results: list[str] = []
                for job_id in job_ids:
                    handle.write(f"[{now_text()}] run {script_path.name} {job_id}\n")
                    handle.flush()
                    result = subprocess.run(
                        [str(script_path), job_id],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=action_subprocess_env(self.registry.root),
                    )
                    results.append(f"{job_id}:{result.returncode}")
                summary = " ".join(results) if results else "no jobs"
                handle.write(f"[{now_text()}] done {label}: {summary}\n")
                handle.flush()
            self.action_state.finish(summary)

        threading.Thread(target=run_jobs, daemon=True).start()
        return f"Started {label}."

    def _start_poll_thread(self, job_ids: list[str], label: str) -> str:
        return self._start_job_action_thread(job_ids, label, POLL_SCRIPT)

    def _start_cancel_thread(self, job: JobRecord) -> str:
        detail = job.job_id
        label = f"cancel selected {job.job_id}"
        if not self.action_state.start(label, detail):
            snapshot = self.action_state.snapshot()
            return f"Action already running: {snapshot['label']}"

        def run_cancel() -> None:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            env = action_subprocess_env(self.registry.root)
            with self.action_state.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{now_text()}] start {label}: {detail}\n")
                handle.write(f"[{now_text()}] run {SSH_SCRIPT.name} /opt/slurm/bin/scancel {job.job_id}\n")
                handle.flush()
                cancel_result = subprocess.run(
                    [str(SSH_SCRIPT), f"/opt/slurm/bin/scancel {job.job_id}"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                handle.write(f"[{now_text()}] run {POLL_SCRIPT.name} {job.job_id}\n")
                handle.flush()
                poll_result = subprocess.run(
                    [str(POLL_SCRIPT), job.job_id],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                summary = f"{job.job_id}:scancel={cancel_result.returncode} poll={poll_result.returncode}"
                handle.write(f"[{now_text()}] done {label}: {summary}\n")
                handle.flush()
            self.action_state.finish(summary)

        threading.Thread(target=run_cancel, daemon=True).start()
        return f"Started {label}."

    def _serve_job_asset(self, parsed: object) -> None:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 3:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, job_id, asset = parts
        job = self.registry.find(job_id)
        if job is None:
            self.send_error(HTTPStatus.NOT_FOUND, f"Unknown job {job_id}")
            return
        if asset == "stdout":
            self._send_path(job, "stdout", job.stdout_path)
            return
        if asset == "stderr":
            self._send_path(job, "stderr", job.stderr_path)
            return
        if asset == "poll-log":
            self._send_path(job, "poll-log", job.poll_log_path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _send_path(self, job: JobRecord, asset: str, path: Path) -> None:
        if not path.exists():
            params = parse_qs(urlparse(self.path).query)
            scope = params["scope"][0] if "scope" in params else source_scope_for_job(job)
            self._send_html(render_missing_job_asset_page(job, asset, path, scope))
            return
        self._send_text(path.read_text(encoding="utf-8", errors="replace"))

    def _redirect(self, path: str, params: dict[str, str]) -> None:
        target = path
        if params:
            target = f"{path}?{urlencode(params)}"
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", target)
        self.end_headers()

    def _send_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_text(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _render_index(self, selected_job_id: str, active_tab: str, sort_key: str, sort_dir: str, limit: str, scope: str) -> str:
        active_jobs, closed_jobs = self.registry.split_jobs()
        scope = normalized_source_scope(scope)
        active_jobs = jobs_for_scope(active_jobs, scope)
        closed_jobs = jobs_for_scope(closed_jobs, scope)
        snapshot = self.action_state.snapshot()
        selected_job = self.registry.find(selected_job_id) if selected_job_id else None
        if selected_job is not None and source_scope_for_job(selected_job) != scope:
            selected_job = None
        toolbar_message = parse_qs(urlparse(self.path).query).get("message", [""])[0]
        jobs = active_jobs if active_tab == "active" else closed_jobs
        jobs = sort_jobs(jobs, active_tab, sort_key, sort_dir)
        limit = normalized_limit(limit)
        visible_jobs = limit_jobs(jobs, limit)
        active_class = "button" if active_tab == "active" else "button tab-muted"
        closed_class = "button" if active_tab == "closed" else "button tab-muted"
        limit_select = render_limit_select(limit)
        cancel_button = ""
        if active_tab == "active":
            cancel_button = '<button class="button" type="submit" formaction="/cancel_selected" formmethod="post">Cancel Selected</button>'
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>HPC Dashboard</title>
<style>
body {{
  font-family: sans-serif;
  margin: 24px;
  color: #18212b;
  background: #f7f8fb;
}}
a {{ color: #124a8a; }}
table {{
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}}
th, td {{
  border: 1px solid #d6dbe4;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}}
th {{
  background: #eef2f8;
}}
.toolbar {{
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}}
.subtoolbar {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0 12px;
}}
.scope-panel {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}}
.scope-toggle {{
  position: relative;
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(90px, 1fr));
  padding: 4px;
  border: 1px solid #c9d4e6;
  border-radius: 999px;
  background: #eef2f8;
}}
.scope-toggle::before {{
  content: "";
  position: absolute;
  top: 4px;
  bottom: 4px;
  left: 4px;
  width: calc(50% - 4px);
  border-radius: 999px;
  background: #124a8a;
  transform: translateX({"100%" if scope == "local" else "0"});
  transition: transform 0.18s ease;
}}
.scope-option {{
  position: relative;
  z-index: 1;
}}
.scope-option input {{
  position: absolute;
  opacity: 0;
  pointer-events: none;
}}
.scope-option span {{
  display: block;
  padding: 8px 18px;
  border-radius: 999px;
  text-align: center;
  font-weight: 600;
  color: #5f6c7a;
  cursor: pointer;
}}
.scope-option input:checked + span {{
  color: #fff;
}}
.toolbar form, .toolbar a {{
  margin: 0;
}}
.button {{
  display: inline-block;
  padding: 8px 12px;
  border: 1px solid #8aa0bd;
  border-radius: 6px;
  background: #fff;
  color: #18212b;
  text-decoration: none;
  cursor: pointer;
}}
.tab-muted {{
  opacity: 0.7;
}}
.grid {{
  display: grid;
  gap: 18px;
}}
.panel {{
  background: #fff;
  border: 1px solid #d6dbe4;
  border-radius: 8px;
  padding: 12px;
}}
.action-status {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0 12px;
  color: #124a8a;
  font-weight: 600;
}}
.spinner {{
  width: 14px;
  height: 14px;
  border: 2px solid #c9d4e6;
  border-top-color: #124a8a;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}}
.updating {{
  color: #124a8a;
  font-weight: 600;
}}
.muted {{
  color: #5f6c7a;
}}
pre {{
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}}
@keyframes spin {{
  from {{ transform: rotate(0deg); }}
  to {{ transform: rotate(360deg); }}
}}
</style>
{render_auto_refresh(snapshot)}
</head>
<body>
<h1>HPC Jobs Dashboard</h1>
<p class="muted">Registry: {escape_text(str(self.registry.path))}</p>
<p>{escape_text(toolbar_message)}</p>
<div class="panel">
  <strong>Action State</strong>
  {render_action_indicator(snapshot)}
  <pre>{escape_text(render_action_snapshot(snapshot))}</pre>
</div>
<div class="grid">
  <form method="get" action="/" class="panel">
    <div class="scope-panel">
      <strong>Source</strong>
      <div class="scope-toggle">
        <label class="scope-option">
          <input type="radio" name="scope" value="hpc"{" checked" if scope == "hpc" else ""} onchange="this.form.submit()">
          <span>HPC</span>
        </label>
        <label class="scope-option">
          <input type="radio" name="scope" value="local"{" checked" if scope == "local" else ""} onchange="this.form.submit()">
          <span>Local</span>
        </label>
      </div>
    </div>
    <div class="subtoolbar">
      <input type="hidden" name="tab" value="{escape_text(active_tab)}">
      <input type="hidden" name="selected" value="{escape_text(selected_job_id)}">
      <input type="hidden" name="sort" value="{escape_text(sort_key)}">
      <input type="hidden" name="dir" value="{escape_text(sort_dir)}">
      <label for="limit">Rows</label>
      {limit_select}
      <input class="button" type="submit" value="Apply">
    </div>
  </form>
  <form id="jobs-form" method="post" action="/poll_selected">
    <div class="toolbar">
      <a class="button" href="/?tab={escape_text(active_tab)}&selected={escape_text(selected_job_id)}&sort={escape_text(sort_key)}&dir={escape_text(sort_dir)}&limit={escape_text(limit)}&scope={escape_text(scope)}">Refresh</a>
      <a class="{active_class}" href="/?tab=active&selected={escape_text(selected_job_id)}&sort={escape_text(sort_key if active_tab == 'active' else default_sort_key('active'))}&dir={escape_text(sort_dir if active_tab == 'active' else 'desc')}&limit={escape_text(limit)}&scope={escape_text(scope)}">Active Jobs ({len(active_jobs)})</a>
      <a class="{closed_class}" href="/?tab=closed&selected={escape_text(selected_job_id)}&sort={escape_text(sort_key if active_tab == 'closed' else default_sort_key('closed'))}&dir={escape_text(sort_dir if active_tab == 'closed' else 'desc')}&limit={escape_text(limit)}&scope={escape_text(scope)}">Closed Jobs ({len(closed_jobs)})</a>
      <input class="button" type="submit" value="Poll Selected">
      <button class="button" type="submit" form="poll-all-active-form" formaction="/poll_all_active" formmethod="post">Poll All Active</button>
      {cancel_button}
      <button class="button" type="submit" formaction="/resubmit_selected" formmethod="post">Resubmit Selected</button>
    </div>
    <input type="hidden" name="tab" value="{escape_text(active_tab)}">
    <input type="hidden" name="sort" value="{escape_text(sort_key)}">
    <input type="hidden" name="dir" value="{escape_text(sort_dir)}">
    <input type="hidden" name="limit" value="{escape_text(limit)}">
    <input type="hidden" name="scope" value="{escape_text(scope)}">
    <section class="panel">
      <h2>{"Active Jobs" if active_tab == "active" else "Closed Jobs"} ({len(jobs)})</h2>
      {render_jobs_table(visible_jobs, selected_job_id, active_tab, sort_key, sort_dir, limit, scope, updating_job_ids(snapshot))}
    </section>
  </form>
</div>
<form id="poll-all-active-form" method="post" action="/poll_all_active">
  <input type="hidden" name="tab" value="{escape_text(active_tab)}">
  <input type="hidden" name="sort" value="{escape_text(sort_key)}">
  <input type="hidden" name="dir" value="{escape_text(sort_dir)}">
  <input type="hidden" name="limit" value="{escape_text(limit)}">
  <input type="hidden" name="scope" value="{escape_text(scope)}">
</form>
<section class="panel">
  <h2>Selected Job</h2>
  {render_selected_job(selected_job, active_tab, scope)}
</section>
</body>
</html>
"""

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def escape_text(value: str) -> str:
    return html.escape(value, quote=True)


def render_action_snapshot(snapshot: dict[str, str]) -> str:
    return "\n".join(
        [
            f"running: {snapshot['running']}",
            f"label: {snapshot['label']}",
            f"detail: {snapshot['detail']}",
            f"started_at: {snapshot['started_at']}",
            f"finished_at: {snapshot['finished_at']}",
        ]
    )


def render_action_indicator(snapshot: dict[str, str]) -> str:
    if snapshot["running"] != "yes":
        return ""
    return (
        '<div class="action-status">'
        '<span class="spinner" aria-hidden="true"></span>'
        f'<span>Running: {escape_text(snapshot["label"])}</span>'
        "</div>"
    )


def render_auto_refresh(snapshot: dict[str, str]) -> str:
    if snapshot["running"] != "yes":
        return ""
    return '<meta http-equiv="refresh" content="2">'


def default_sort_key(active_tab: str) -> str:
    if active_tab == "closed":
        return "finished_at"
    return "submitted_at"


def normalized_sort_key(sort_key: str, active_tab: str) -> str:
    if sort_key in SORT_COLUMNS:
        return sort_key
    return default_sort_key(active_tab)


def normalized_sort_dir(sort_dir: str) -> str:
    if sort_dir == "asc":
        return "asc"
    return "desc"


def normalized_limit(limit: str) -> str:
    if limit in LIMIT_OPTIONS:
        return limit
    return DEFAULT_LIMIT


def normalized_source_scope(scope: str) -> str:
    if scope in SOURCE_SCOPES:
        return scope
    return DEFAULT_SOURCE_SCOPE


def is_local_job(job: JobRecord) -> bool:
    return job.resolved_input_method == "local_train_retry" or job.job_id.startswith("local-")


def source_scope_for_job(job: JobRecord) -> str:
    if is_local_job(job):
        return "local"
    return "hpc"


def jobs_for_scope(jobs: list[JobRecord], scope: str) -> list[JobRecord]:
    scope = normalized_source_scope(scope)
    return [job for job in jobs if source_scope_for_job(job) == scope]


def limit_jobs(jobs: list[JobRecord], limit: str) -> list[JobRecord]:
    if limit == "all":
        return jobs
    return jobs[: int(limit)]


def sort_value(job: JobRecord, sort_key: str) -> tuple[int, str]:
    if sort_key == "job_id":
        value = job.job_id
    elif sort_key == "state":
        value = job.state
    elif sort_key == "job_name":
        value = job.job_name
    elif sort_key == "submitted_at":
        value = job.submitted_at
    elif sort_key == "last_polled_at":
        value = job.last_polled_at
    elif sort_key == "exit_code":
        value = job.exit_code
    else:
        value = job.finished_at
    return (1 if value in {"", "-"} else 0, value)


def sort_jobs(jobs: list[JobRecord], active_tab: str, sort_key: str, sort_dir: str) -> list[JobRecord]:
    sort_key = normalized_sort_key(sort_key, active_tab)
    sort_dir = normalized_sort_dir(sort_dir)
    reverse = sort_dir == "desc"
    return sorted(jobs, key=lambda job: sort_value(job, sort_key), reverse=reverse)


def header_link(label: str, column: str, active_tab: str, selected_job_id: str, sort_key: str, sort_dir: str, limit: str, scope: str) -> str:
    current_key = normalized_sort_key(sort_key, active_tab)
    current_dir = normalized_sort_dir(sort_dir)
    limit = normalized_limit(limit)
    next_dir = "desc"
    arrow = ""
    if current_key == column:
        next_dir = "asc" if current_dir == "desc" else "desc"
        arrow = " ↓" if current_dir == "desc" else " ↑"
    href = (
        f"/?tab={escape_text(active_tab)}"
        f"&selected={escape_text(selected_job_id)}"
        f"&sort={escape_text(column)}"
        f"&dir={escape_text(next_dir)}"
        f"&limit={escape_text(limit)}"
        f"&scope={escape_text(scope)}"
    )
    return f'<a href="{href}">{escape_text(label + arrow)}</a>'


def render_limit_select(limit: str) -> str:
    limit = normalized_limit(limit)
    options = []
    for option in LIMIT_OPTIONS:
        selected = " selected" if option == limit else ""
        options.append(f'<option value="{escape_text(option)}"{selected}>{escape_text(option)}</option>')
    return f'<select id="limit" name="limit">{"".join(options)}</select>'


def updating_job_ids(snapshot: dict[str, str]) -> set[str]:
    if snapshot["running"] != "yes":
        return set()
    return set(snapshot["detail"].split())


def render_poll_cell(job: JobRecord, updating_ids: set[str]) -> str:
    if job.job_id not in updating_ids:
        return escape_text(job.display_last_polled_at)
    return '<span class="updating">UPDATING...</span>'


def render_jobs_table(
    jobs: list[JobRecord],
    selected_job_id: str,
    active_tab: str,
    sort_key: str,
    sort_dir: str,
    limit: str,
    scope: str,
    updating_ids: set[str],
) -> str:
    sort_key = normalized_sort_key(sort_key, active_tab)
    sort_dir = normalized_sort_dir(sort_dir)
    limit = normalized_limit(limit)
    if not jobs:
        return "<p class=\"muted\">No jobs.</p>"
    rows = []
    for job in jobs:
        checked = " checked" if job.job_id == selected_job_id else ""
        rows.append(
            "<tr>"
            f"<td><input type=\"radio\" name=\"job_id\" value=\"{escape_text(job.job_id)}\"{checked}></td>"
            f"<td><a href=\"/?tab={escape_text(active_tab)}&selected={escape_text(job.job_id)}&sort={escape_text(sort_key)}&dir={escape_text(sort_dir)}&limit={escape_text(limit)}&scope={escape_text(scope)}\">{escape_text(job.job_id)}</a></td>"
            f"<td>{escape_text(source_scope_for_job(job))}</td>"
            f"<td>{escape_text(job.state)}</td>"
            f"<td>{escape_text(job.job_name)}</td>"
            f"<td>{escape_text(job.display_submitted_at)}</td>"
            f"<td>{render_poll_cell(job, updating_ids)}</td>"
            f"<td>{escape_text(job.exit_code)}</td>"
            f"<td>{escape_text(job.display_finished_at)}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr>"
        "<th>Select</th>"
        f"<th>{header_link('Job ID', 'job_id', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        "<th>Source</th>"
        f"<th>{header_link('State', 'state', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        f"<th>{header_link('Job', 'job_name', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        f"<th>{header_link('Submitted', 'submitted_at', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        f"<th>{header_link('POLL', 'last_polled_at', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        f"<th>{header_link('Exit', 'exit_code', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        f"<th>{header_link('Finished', 'finished_at', active_tab, selected_job_id, sort_key, sort_dir, limit, scope)}</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def render_selected_job(job: JobRecord | None, active_tab: str, scope: str) -> str:
    if job is None:
        return "<p class=\"muted\">Select a job to inspect local paths and logs.</p>"
    job_meta = read_key_value_file(job.job_meta_path)
    worker_meta = read_key_value_file(job.worker_meta_path)
    lines = [f"{key}: {value}" for key, value in selected_job_summary_pairs(job)]
    filtered_job_meta = filtered_job_meta_pairs(job_meta)
    filtered_worker_meta = filtered_worker_meta_pairs(worker_meta)
    if job_meta:
        if filtered_job_meta:
            lines.append("")
            lines.append("[job.meta]")
            lines.extend(f"{key}: {value}" for key, value in filtered_job_meta)
    if worker_meta:
        if filtered_worker_meta:
            lines.append("")
            lines.append("[worker.meta]")
            lines.extend(f"{key}: {value}" for key, value in filtered_worker_meta)
    links = [
        f"<a href=\"/jobs/{escape_text(job.job_id)}/stdout?scope={escape_text(scope)}&tab={escape_text(active_tab)}\">stdout</a>",
        f"<a href=\"/jobs/{escape_text(job.job_id)}/stderr?scope={escape_text(scope)}&tab={escape_text(active_tab)}\">stderr</a>",
        f"<a href=\"/jobs/{escape_text(job.job_id)}/poll-log?scope={escape_text(scope)}&tab={escape_text(active_tab)}\">poll.log</a>",
    ]
    if job.has_submit_provenance:
        links.append("resubmit: registry provenance available")
    return f"<p>{' | '.join(links)}</p><pre>{escape_text(chr(10).join(lines))}</pre>"


def selected_job_summary_pairs(job: JobRecord) -> list[tuple[str, str]]:
    return [
        ("job_id", job.job_id),
        ("state", job.state),
        ("exit_code", job.exit_code),
        ("job_name", job.job_name),
        ("submitted_at", job.submitted_at),
        ("finished_at", job.finished_at),
        ("last_polled_at", job.last_polled_at),
        ("sbatch_file", job.sbatch_file),
        ("remote_script", job.remote_script),
    ]


def filtered_job_meta_pairs(job_meta: dict[str, str]) -> list[tuple[str, str]]:
    hidden = {
        "input_method",
        "submit_argv",
        "job_id",
        "job_name",
        "submitted_at",
        "sbatch_file",
        "remote_script",
        "job_dir",
        "stdout",
        "stderr",
        "job_meta",
        "worker_meta",
        "worker_log",
        "poll_log",
    }
    preferred = ("script_args", "poll_schedule", "log_out_template", "log_err_template")
    pairs: list[tuple[str, str]] = []
    for key in preferred:
        if key in job_meta and job_meta[key] not in {"", "-"}:
            pairs.append((key, job_meta[key]))
    for key, value in job_meta.items():
        if key in hidden or key in preferred or value in {"", "-"}:
            continue
        pairs.append((key, value))
    return pairs


def filtered_worker_meta_pairs(worker_meta: dict[str, str]) -> list[tuple[str, str]]:
    preferred = (
        "worker_pid",
        "worker_state",
        "started_at",
        "poll_schedule",
        "poll_schedule_source",
        "final_state",
        "final_exit",
        "finished_at",
    )
    pairs: list[tuple[str, str]] = []
    for key in preferred:
        if key in worker_meta and worker_meta[key] not in {"", "-"}:
            pairs.append((key, worker_meta[key]))
    return pairs


def alternate_local_log_paths(job: JobRecord, asset: str) -> list[Path]:
    if not job.job_dir.exists():
        return []
    if asset == "stdout":
        suffix = f".o{job.job_id}"
    elif asset == "stderr":
        suffix = f".e{job.job_id}"
    else:
        return []
    return sorted(path for path in job.job_dir.iterdir() if path.is_file() and path.name.endswith(suffix))


def render_missing_job_asset_page(job: JobRecord, asset: str, path: Path, scope: str) -> str:
    tab = "closed" if job.closed else "active"
    back_href = f"/?tab={escape_text(tab)}&selected={escape_text(job.job_id)}&scope={escape_text(scope)}"
    poll_cmd = f"agent/hpc/cli/hpc_poll_logs.sh {job.job_id}"
    raw_paths = alternate_local_log_paths(job, asset)
    if raw_paths:
        status_message = "Canonical fetched copy is missing, but a raw local Slurm log file already exists."
        hint_message = "Poll/fetch can still be useful to create or refresh the canonical std.out/std.err copy."
        raw_block = "<p>Raw local file:</p><pre>" + escape_text("\n".join(str(raw_path) for raw_path in raw_paths)) + "</pre>"
    else:
        status_message = "Requested file is not present locally yet."
        hint_message = "Usual fix: run a poll/fetch for this job, then retry the link. There can be a short lag after polling before canonical files appear."
        raw_block = ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Missing {escape_text(asset)} for {escape_text(job.job_id)}</title>
</head>
<body>
<h1>Missing {escape_text(asset)} for job {escape_text(job.job_id)}</h1>
<p>{escape_text(status_message)}</p>
<p><code>{escape_text(str(path))}</code></p>
{raw_block}
<p>Last poll: {escape_text(job.display_last_polled_at or "never")}</p>
<p>{escape_text(hint_message)}</p>
<p><code>{escape_text(poll_cmd)}</code></p>
<p><a href="{back_href}">Back to selected job</a></p>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local stdlib web dashboard for HPC job registry.")
    parser.add_argument("--host", default=os.environ.get("HPC_DASHBOARD_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HPC_DASHBOARD_PORT", DEFAULT_PORT)))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--meta-file", type=Path, required=True)
    return parser.parse_args()


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


def build_server(args: argparse.Namespace) -> tuple[ThreadingHTTPServer, str]:
    registry = JobRegistry()
    action_state = ActionState(args.state_dir)
    DashboardHandler.registry = registry
    DashboardHandler.action_state = action_state
    DashboardHandler.state_dir = args.state_dir
    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    actual_host, actual_port = httpd.server_address[:2]
    url = write_meta(args.meta_file, actual_host, actual_port, args.state_dir, registry)
    return httpd, url


def main() -> int:
    args = parse_args()
    httpd, url = build_server(args)

    def stop_handler(signum: int, frame: object) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    print(url, flush=True)
    httpd.serve_forever(poll_interval=0.5)
    httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
