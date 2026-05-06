from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

READY = "ready"
NOT_READY = "not_ready"
REPAIRABLE = "repairable"
FAILED = "failed"
BLOCKED = "blocked"
TIMED_OUT = "timed_out"
SUBMITTED = "submitted"
RUNNING = "running"
COMPLETED = "completed"
DEBUGGING = "debugging"
REPAIR_SUBMITTED = "repair_submitted"
DEBUG_FAILED = "debug_failed"

STATUSES = (
    READY,
    NOT_READY,
    REPAIRABLE,
    FAILED,
    BLOCKED,
    TIMED_OUT,
    SUBMITTED,
    RUNNING,
    COMPLETED,
    DEBUGGING,
    REPAIR_SUBMITTED,
    DEBUG_FAILED,
)


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
    error_code: str | None = None
    next_action: str | None = None
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return omit_nones(asdict(self))


def omit_nones(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: omit_nones(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_nones(item) for item in value]
    return value
