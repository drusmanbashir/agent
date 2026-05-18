from __future__ import annotations

import csv
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from agent.storage_roots import storage_root

REGISTRY_COLUMNS = (
    "job_id",
    "submitted_at",
    "sbatch_file",
    "job_name",
    "remote_script",
    "state",
    "exit_code",
    "finished_at",
    "last_polled_at",
    "input_method",
    "submit_argv",
)

TERMINAL_STATE_PREFIXES = (
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
)


def default_logs_root() -> Path:
    return storage_root("hpc_logs")


def registry_path(root: Path | None = None) -> Path:
    return (root or default_logs_root()) / "job_registry.tsv"


def archive_registry_path(root: Path | None = None) -> Path:
    return (root or default_logs_root()) / "job_registry.archive.tsv"


def is_terminal_state(state: str, finished_at: str) -> bool:
    if finished_at not in {"", "-"}:
        return True
    return any(state.startswith(prefix) for prefix in TERMINAL_STATE_PREFIXES)


def read_key_value_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def parse_iso_datetime(value: str, fallback_tzinfo=None) -> datetime | None:
    if value in {"", "-"}:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None and fallback_tzinfo is not None:
        return parsed.replace(tzinfo=fallback_tzinfo)
    return parsed


def format_british_datetime(value: str) -> str:
    if value in {"", "-"}:
        return ""
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return value
    return parsed.strftime("%d/%m/%Y %H:%M:%S")


@dataclass(slots=True)
class JobRecord:
    job_id: str
    submitted_at: str
    sbatch_file: str
    job_name: str
    remote_script: str
    state: str
    exit_code: str
    finished_at: str
    last_polled_at: str
    input_method: str
    submit_argv: str
    root: Path = field(repr=False)
    extras: tuple[str, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def from_row(cls, row: list[str], root: Path) -> JobRecord:
        padded = row[: len(REGISTRY_COLUMNS)] + ["-"] * max(0, len(REGISTRY_COLUMNS) - len(row))
        return cls(*padded[: len(REGISTRY_COLUMNS)], root=root, extras=tuple(row[len(REGISTRY_COLUMNS) :]))

    def to_row(self) -> list[str]:
        return [
            self.job_id,
            self.submitted_at,
            self.sbatch_file,
            self.job_name,
            self.remote_script,
            self.state,
            self.exit_code,
            self.finished_at,
            self.last_polled_at,
            self.input_method,
            self.submit_argv,
            *self.extras,
        ]

    @property
    def job_dir(self) -> Path:
        return self.root / self.job_id

    @property
    def closed(self) -> bool:
        return is_terminal_state(self.state, self.finished_at)

    @property
    def stdout_path(self) -> Path:
        return self.job_dir / "std.out"

    @property
    def stderr_path(self) -> Path:
        return self.job_dir / "std.err"

    @property
    def job_meta_path(self) -> Path:
        return self.job_dir / "job.meta"

    @property
    def worker_meta_path(self) -> Path:
        return self.job_dir / "worker.meta"

    @property
    def orch_path(self) -> Path:
        return self.job_dir / "orch.json"

    @property
    def worker_log_path(self) -> Path:
        return self.job_dir / "worker.log"

    @property
    def poll_log_path(self) -> Path:
        return self.job_dir / "poll.log"

    @property
    def display_finished_at(self) -> str:
        return format_british_datetime(self.finished_at)

    @property
    def display_last_polled_at(self) -> str:
        return format_british_datetime(self.last_polled_at)

    @property
    def display_submitted_at(self) -> str:
        return format_british_datetime(self.submitted_at)

    @property
    def resolved_input_method(self) -> str:
        return self.input_method

    @property
    def resolved_submit_argv(self) -> str:
        return self.submit_argv

    @property
    def has_submit_provenance(self) -> bool:
        return self.resolved_input_method not in {"", "-"} and self.resolved_submit_argv not in {"", "-"}

    def detail_pairs(self) -> list[tuple[str, str]]:
        pairs = [
            ("job_id", self.job_id),
            ("state", self.state),
            ("exit_code", self.exit_code),
            ("job_name", self.job_name),
            ("submitted_at", self.submitted_at),
            ("finished_at", self.finished_at),
            ("last_polled_at", self.last_polled_at),
            ("sbatch_file", self.sbatch_file),
            ("remote_script", self.remote_script),
            ("job_dir", str(self.job_dir)),
            ("stdout", str(self.stdout_path)),
            ("stderr", str(self.stderr_path)),
            ("job_meta", str(self.job_meta_path)),
            ("worker_meta", str(self.worker_meta_path)),
            ("worker_log", str(self.worker_log_path)),
            ("poll_log", str(self.poll_log_path)),
        ]
        if self.resolved_input_method not in {"", "-"}:
            pairs.append(("input_method", self.resolved_input_method))
        if self.resolved_submit_argv not in {"", "-"}:
            pairs.append(("submit_argv", self.resolved_submit_argv))
        return pairs


class JobRegistry:
    def __init__(self, root: Path | None = None):
        self.root = (root or default_logs_root()).expanduser()
        self.path = registry_path(self.root)
        self.archive_path = archive_registry_path(self.root)
        self.lock_path = Path(f"{self.path}.lock")

    def load(self) -> list[JobRecord]:
        if not self.path.exists():
            return []
        rows: list[JobRecord] = []
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            for row in reader:
                if not row:
                    continue
                if row[0] == "job_id":
                    continue
                rows.append(JobRecord.from_row(row, self.root))
        return rows

    def split_jobs(self) -> tuple[list[JobRecord], list[JobRecord]]:
        active: list[JobRecord] = []
        closed: list[JobRecord] = []
        for job in self.load():
            (closed if job.closed else active).append(job)
        active.sort(key=lambda job: (job.submitted_at, job.job_id), reverse=True)
        closed.sort(
            key=lambda job: (job.finished_at if job.finished_at != "-" else job.submitted_at, job.job_id),
            reverse=True,
        )
        return active, closed

    def active_jobs(self) -> list[JobRecord]:
        return self.split_jobs()[0]

    def closed_jobs(self) -> list[JobRecord]:
        return self.split_jobs()[1]

    def find(self, job_id: str) -> JobRecord | None:
        for job in self.load():
            if job.job_id == job_id:
                return job
        return None

    def add(self, job: JobRecord) -> JobRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locked():
            jobs = self.load()
            for existing in jobs:
                if existing.job_id == job.job_id:
                    return existing
            jobs.append(job)
            self._write_rows(self.path, jobs)
        return job

    def update_status(self, job_id: str, state: str, exit_code: str, finished_at: str) -> JobRecord | None:
        with self._locked():
            jobs = self.load()
            updated: JobRecord | None = None
            rewritten: list[JobRecord] = []
            for job in jobs:
                if job.job_id == job_id:
                    updated = JobRecord(
                        job_id=job.job_id,
                        submitted_at=job.submitted_at,
                        sbatch_file=job.sbatch_file,
                        job_name=job.job_name,
                        remote_script=job.remote_script,
                        state=state,
                        exit_code=exit_code,
                        finished_at=finished_at,
                        last_polled_at=job.last_polled_at,
                        input_method=job.input_method,
                        submit_argv=job.submit_argv,
                        root=job.root,
                        extras=job.extras,
                    )
                    rewritten.append(updated)
                else:
                    rewritten.append(job)
            self._write_rows(self.path, rewritten)
        return updated

    def update_polled(self, job_id: str, polled_at: str) -> JobRecord | None:
        with self._locked():
            jobs = self.load()
            updated: JobRecord | None = None
            rewritten: list[JobRecord] = []
            for job in jobs:
                if job.job_id == job_id:
                    updated = JobRecord(
                        job_id=job.job_id,
                        submitted_at=job.submitted_at,
                        sbatch_file=job.sbatch_file,
                        job_name=job.job_name,
                        remote_script=job.remote_script,
                        state=job.state,
                        exit_code=job.exit_code,
                        finished_at=job.finished_at,
                        last_polled_at=polled_at,
                        input_method=job.input_method,
                        submit_argv=job.submit_argv,
                        root=job.root,
                        extras=job.extras,
                    )
                    rewritten.append(updated)
                else:
                    rewritten.append(job)
            self._write_rows(self.path, rewritten)
        return updated

    def archive_jobs(self, days: int = 14, now: datetime | None = None) -> int:
        current = now or datetime.now().astimezone()
        cutoff = current - timedelta(days=days)
        keep: list[JobRecord] = []
        archive: list[JobRecord] = []
        for job in self.load():
            reference_time = self._archive_reference_dt(job, current)
            if job.closed and reference_time is not None and reference_time < cutoff:
                archive.append(job)
            else:
                keep.append(job)
        if not archive:
            return 0
        self.root.mkdir(parents=True, exist_ok=True)
        self._append_rows(self.archive_path, archive)
        self._write_rows(self.path, keep)
        return len(archive)

    def _archive_reference_dt(self, job: JobRecord, current: datetime) -> datetime | None:
        finished_at = parse_iso_datetime(job.finished_at, current.tzinfo)
        if finished_at is not None:
            return finished_at
        return parse_iso_datetime(job.submitted_at, current.tzinfo)

    def _write_rows(self, path: Path, jobs: list[JobRecord]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            for job in jobs:
                writer.writerow(job.to_row())

    def _append_rows(self, path: Path, jobs: list[JobRecord]) -> None:
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            for job in jobs:
                writer.writerow(job.to_row())

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
