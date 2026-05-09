from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class TrainRequest(BaseModel):
    project: str
    plan_id: int
    mode: Literal["local", "hpc"] = "local"
    devices: str = "1"
    learning_rate: float | None = 0.01
    batch_size: int = 4
    fold: int | None = 0
    epochs: int = 500
    compiled: bool = False
    profiler: bool = False
    wandb: bool = True
    run_name: str | None = "none"
    description: str | None = None
    cache_rate: float = 0.0
    ds_type: str | None = None
    val_every_n_epochs: int = 2
    train_indices: int | None = None
    bsf: bool = True
    max_retries: int = 3
    step: int = 1
    min_bs: int = 1
    provider: str = "ollama"
    model: str = ""
    escalation_target: str = ""

    def service_kwargs(self) -> dict[str, Any]:
        return {
            "project_title": self.project,
            "plan": self.plan_id,
            "mode": self.mode,
            "devices": self.devices,
            "learning_rate": self.learning_rate,
            "batch_size": self.batch_size,
            "fold": self.fold,
            "epochs": self.epochs,
            "compiled": self.compiled,
            "profiler": self.profiler,
            "wandb": self.wandb,
            "run_name": normalize_run_name(self.run_name),
            "description": self.description,
            "cache_rate": self.cache_rate,
            "ds_type": self.ds_type,
            "val_every_n_epochs": self.val_every_n_epochs,
            "train_indices": self.train_indices,
            "bsf": self.bsf,
            "max_retries": self.max_retries,
            "step": self.step,
            "min_bs": self.min_bs,
            "provider": self.provider,
            "model": self.model,
            "escalation_target": self.escalation_target,
        }


def normalize_run_name(run_name: str | None) -> str | None:
    if run_name is None or run_name in {"", "none", "null"}:
        return None
    return run_name
