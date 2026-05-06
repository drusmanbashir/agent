from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from agent.control_plane.service import (
    datasource_ready as datasource_ready_service,
    local_job_crash_packet as local_job_crash_packet_service,
    local_job_list as local_job_list_service,
    local_job_status as local_job_status_service,
    orchestrator_train_request as orchestrator_train_request_service,
    project_ready as project_ready_service,
)

mcp = FastMCP("agent-control-plane")


def _tool_result(payload: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, indent=2, sort_keys=True))],
        structuredContent=payload,
    )


@mcp.tool()
def datasource_ready(
    name: str,
    mode: Literal["local", "hpc"] = "local",
    ensure: bool = False,
    num_processes: Annotated[int, Field(ge=1)] = 1,
    job_id: str | None = None,
) -> CallToolResult:
    """Inspect, repair locally, submit to HPC, or poll readiness for a FRAN datasource fg_voxels.h5 prerequisite."""
    return _tool_result(
        datasource_ready_service(
            name=name,
            mode=mode,
            ensure=ensure,
            num_processes=num_processes,
            job_id=job_id,
        )
    )


@mcp.tool()
def project_ready(
    title: str,
    mnemonic: str,
    datasources: tuple[str, ...] = (),
    mode: Literal["local", "hpc"] = "local",
    ensure: bool = False,
    num_processes: Annotated[int, Field(ge=1)] = 1,
    test: bool = False,
    job_id: str | None = None,
) -> CallToolResult:
    """Inspect, repair locally, submit to HPC, or poll readiness for FRAN project registration against datasource prerequisites."""
    return _tool_result(
        project_ready_service(
            title=title,
            mnemonic=mnemonic,
            datasources=list(datasources),
            mode=mode,
            ensure=ensure,
            num_processes=num_processes,
            test=test,
            job_id=job_id,
        )
    )


@mcp.tool()
def orchestrator_train_request(
    project_title: str,
    plan: int,
    devices: str = "1",
    learning_rate: float | None = None,
    batch_size: Annotated[int, Field(ge=1)] = 4,
    fold: int | None = None,
    epochs: Annotated[int, Field(ge=1)] = 500,
    compiled: bool = False,
    profiler: bool = False,
    wandb: bool = True,
    run_name: str | None = None,
    description: str | None = None,
    cache_rate: float = 0.0,
    ds_type: str | None = None,
    val_every_n_epochs: Annotated[int, Field(ge=1)] = 5,
    train_indices: int | None = None,
    bsf: bool = True,
    max_retries: Annotated[int, Field(ge=1)] = 3,
    step: Annotated[int, Field(ge=1)] = 1,
    min_bs: Annotated[int, Field(ge=1)] = 1,
    provider: str = "ollama",
    model: str = "",
    escalation_target: str = "",
) -> CallToolResult:
    """Resolve a FRAN train intent into a workflow breakpoint or submit local train when prerequisites are ready."""
    return _tool_result(
        orchestrator_train_request_service(
            project_title=project_title,
            plan=plan,
            devices=devices,
            learning_rate=learning_rate,
            batch_size=batch_size,
            fold=fold,
            epochs=epochs,
            compiled=compiled,
            profiler=profiler,
            wandb=wandb,
            run_name=run_name,
            description=description,
            cache_rate=cache_rate,
            ds_type=ds_type,
            val_every_n_epochs=val_every_n_epochs,
            train_indices=train_indices,
            bsf=bsf,
            max_retries=max_retries,
            step=step,
            min_bs=min_bs,
            provider=provider,
            model=model,
            escalation_target=escalation_target,
        )
    )


@mcp.tool()
def local_job_status(job_id: str) -> CallToolResult:
    """Poll one local shared-registry job and return the current control-plane status."""
    return _tool_result(local_job_status_service(job_id))


@mcp.tool()
def local_job_list(limit: Annotated[int, Field(ge=1, le=200)] = 25) -> CallToolResult:
    """List recent local jobs mirrored into the shared registry."""
    return _tool_result(local_job_list_service(limit))


@mcp.tool()
def local_job_crash_packet(
    job_id: str,
    tail_lines: Annotated[int, Field(ge=1, le=2000)] = 200,
) -> CallToolResult:
    """Build a failure packet from local shared-registry metadata and stdout/stderr tails."""
    return _tool_result(local_job_crash_packet_service(job_id, tail_lines))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
