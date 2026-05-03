from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    source_root: Path
    agent_root: Path

    @property
    def source_guidelines(self) -> Path:
        return self.source_root / "guidelines"

    @property
    def source_cpd(self) -> Path:
        return self.source_root / "cpd"

    @property
    def source_evidence(self) -> Path:
        return self.source_root / "evidence"

    @property
    def rules_dir(self) -> Path:
        return self.agent_root / "rules"

    @property
    def index_dir(self) -> Path:
        return self.agent_root / "index"

    @property
    def evidence_email_dir(self) -> Path:
        return self.agent_root / "evidence" / "email"

    @property
    def logs_dir(self) -> Path:
        return self.agent_root / "logs"

    def ensure_dirs(self) -> None:
        for p in (self.rules_dir, self.index_dir, self.evidence_email_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)


def assert_read_only_source(source_root: Path) -> None:
    if not source_root.exists():
        raise FileNotFoundError(f"source_root does not exist: {source_root}")


def assert_within_agent_root(agent_root: Path, target: Path) -> None:
    agent_root = agent_root.resolve()
    target = target.resolve()
    if agent_root not in target.parents and target != agent_root:
        raise PermissionError(f"refusing to write outside agent_root: {target}")
