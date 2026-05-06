from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

READY = "ready"
NOT_READY = "not_ready"
REPAIRABLE = "repairable"
FAILED = "failed"
SUBMITTED = "submitted"
RUNNING = "running"

STATUSES = (READY, NOT_READY, REPAIRABLE, FAILED, SUBMITTED, RUNNING)


@dataclass(slots=True)
class JobInfo:
    job_id: str
    command: list[str] = field(default_factory=list)
    job_dir: str | None = None
    state: str | None = None
    dashboard_url: str | None = None


@dataclass(slots=True)
class StatusResult:
    target: str
    name: str
    mode: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    job: JobInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.job is None:
            data.pop("job")
        return data
