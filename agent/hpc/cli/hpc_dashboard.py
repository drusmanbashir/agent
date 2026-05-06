#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.job_registry import JobRecord, JobRegistry, read_key_value_file

POLL_SCRIPT = REPO_ROOT / "cli" / "hpc_poll_logs.sh"


def poll_subprocess_env(logs_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    root = str(logs_root)
    env["HPC_LOGS_LOCAL_ROOT"] = root
    env["HPC_POLL_LOG_DEST"] = root
    return env


def display_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class DashboardApp:
    columns = ("job_id", "state", "job_name", "submitted_at", "last_polled_at", "exit_code", "finished_at")

    def __init__(self, root: tk.Tk, registry: JobRegistry):
        self.root = root
        self.registry = registry
        self.selected_job_id = ""
        self.status_var = tk.StringVar(value=f"Registry: {self.registry.path}")
        self.active_frame, self.active_tree = self._build_tree("Active Jobs")
        self.closed_frame, self.closed_tree = self._build_tree("Closed Jobs")
        self._build_layout()
        self.refresh()

    def _build_tree(self, title: str) -> tuple[ttk.LabelFrame, ttk.Treeview]:
        frame = ttk.LabelFrame(self.root, text=title, padding=8)
        tree = ttk.Treeview(frame, columns=self.columns, show="headings", height=16)
        tree.heading("job_id", text="Job ID")
        tree.heading("state", text="State")
        tree.heading("job_name", text="Job")
        tree.heading("submitted_at", text="Submitted")
        tree.heading("last_polled_at", text="Poll")
        tree.heading("exit_code", text="Exit")
        tree.heading("finished_at", text="Finished")
        tree.column("job_id", width=90, anchor="w")
        tree.column("state", width=150, anchor="w")
        tree.column("job_name", width=180, anchor="w")
        tree.column("submitted_at", width=170, anchor="w")
        tree.column("last_polled_at", width=170, anchor="w")
        tree.column("exit_code", width=70, anchor="w")
        tree.column("finished_at", width=170, anchor="w")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree.bind("<<TreeviewSelect>>", self._on_select)
        return frame, tree

    def _build_layout(self) -> None:
        self.root.title("HPC Jobs Dashboard")
        self.root.geometry("1650x900")
        self.root.minsize(1100, 700)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.root.rowconfigure(3, weight=0)
        self.root.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(toolbar, text="Poll Selected Job Now", command=self.poll_selected).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Poll All Active Now", command=self.poll_all_active).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Open/Show Job Dir", command=self.open_selected_dir).pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="right")
        toolbar.grid(row=0, column=0, sticky="ew")

        notebook = ttk.Notebook(self.root)
        notebook.add(self.active_frame, text="Active Jobs")
        notebook.add(self.closed_frame, text="Closed Jobs")
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)

        detail_frame = ttk.LabelFrame(self.root, text="Selected Job", padding=8)
        detail_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 6))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.detail = tk.Text(detail_frame, height=14, wrap="none")
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set, state="disabled")
        self.detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")

        hint = ttk.Label(
            self.root,
            padding=(10, 0, 10, 10),
            text="Poll actions use cli/hpc_poll_logs.sh in background threads. Details always show the resolved local job/log paths.",
        )
        hint.grid(row=3, column=0, sticky="ew")

    def _rows_for(self, jobs: list[JobRecord]) -> list[tuple[str, tuple[str, ...]]]:
        return [
            (
                job.job_id,
                (
                    job.job_id,
                    job.state,
                    job.job_name,
                    job.display_submitted_at,
                    job.display_last_polled_at,
                    job.exit_code,
                    job.display_finished_at,
                ),
            )
            for job in jobs
        ]

    def refresh(self) -> None:
        active_jobs, closed_jobs = self.registry.split_jobs()
        self._replace_tree_rows(self.active_tree, self._rows_for(active_jobs))
        self._replace_tree_rows(self.closed_tree, self._rows_for(closed_jobs))
        self.status_var.set(
            f"Registry: {self.registry.path} | active={len(active_jobs)} closed={len(closed_jobs)}"
        )
        if self.selected_job_id:
            self._render_selected_job(self.selected_job_id)

    def _replace_tree_rows(self, tree: ttk.Treeview, rows: list[tuple[str, tuple[str, ...]]]) -> None:
        selected = tree.selection()
        for item in tree.get_children():
            tree.delete(item)
        for item_id, values in rows:
            tree.insert("", "end", iid=item_id, values=values)
        if selected and selected[0] in tree.get_children():
            tree.selection_set(selected[0])

    def _on_select(self, event: tk.Event) -> None:
        tree = event.widget
        selection = tree.selection()
        if not selection:
            return
        if tree is self.active_tree:
            self.closed_tree.selection_remove(*self.closed_tree.selection())
        else:
            self.active_tree.selection_remove(*self.active_tree.selection())
        self.selected_job_id = selection[0]
        self._render_selected_job(self.selected_job_id)

    def _selected_job(self) -> JobRecord | None:
        if not self.selected_job_id:
            return None
        return self.registry.find(self.selected_job_id)

    def _render_selected_job(self, job_id: str) -> None:
        job = self.registry.find(job_id)
        if job is None:
            self._set_detail("Selected job no longer exists in the registry.")
            return
        job_meta = read_key_value_file(job.job_meta_path)
        worker_meta = read_key_value_file(job.worker_meta_path)
        lines = [f"{key}: {value}" for key, value in job.detail_pairs()]
        if job_meta:
            lines.append("")
            lines.append("[job.meta]")
            lines.extend(f"{key}: {value}" for key, value in job_meta.items())
        if worker_meta:
            lines.append("")
            lines.append("[worker.meta]")
            lines.extend(f"{key}: {value}" for key, value in worker_meta.items())
        self._set_detail("\n".join(lines))

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def poll_selected(self) -> None:
        job = self._selected_job()
        if job is None:
            self.status_var.set("Select a job first.")
            return
        self._run_poll_jobs([job])

    def poll_all_active(self) -> None:
        jobs = self.registry.active_jobs()
        if not jobs:
            self.status_var.set("No active jobs to poll.")
            return
        self._run_poll_jobs(jobs)

    def _run_poll_jobs(self, jobs: list[JobRecord]) -> None:
        self.status_var.set(f"Polling {len(jobs)} job(s) in background...")

        def worker() -> None:
            results = []
            for job in jobs:
                result = subprocess.run(
                    [str(POLL_SCRIPT), job.job_id],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    env=poll_subprocess_env(self.registry.root),
                )
                results.append((job.job_id, result.returncode))
            self.root.after(0, lambda: self._finish_poll(results))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_poll(self, results: list[tuple[str, int]]) -> None:
        self.refresh()
        parts = [f"{job_id}:{code}" for job_id, code in results]
        self.status_var.set(f"Poll complete | {' '.join(parts)}")
        job = self._selected_job()
        if job is not None:
            self._render_selected_job(job.job_id)

    def open_selected_dir(self) -> None:
        job = self._selected_job()
        if job is None:
            self.status_var.set("Select a job first.")
            return
        path = str(job.job_dir)
        opener = shutil.which("xdg-open")
        if opener and display_available():
            subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.status_var.set(f"Opened {path}")
            return
        self.status_var.set(f"Job dir: {path}")
        self._render_selected_job(job.job_id)


def main() -> int:
    if not display_available():
        print("No graphical display detected. Set DISPLAY or WAYLAND_DISPLAY to launch the dashboard.", file=sys.stderr)
        return 2
    root = tk.Tk()
    DashboardApp(root, JobRegistry())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
