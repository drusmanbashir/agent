# Orchestration

## Purpose
This document is top-level map for how `agent` launches work, tracks work, and gathers evidence. Keep durable structure here. Keep implementation detail in code.

## System Boundary
`agent` has three operational layers:

1. Request surface
   User-facing commands, prompts, and thin wrappers decide intent and choose canonical path.

2. Control plane
   Control-plane code creates job identity, records provenance, launches workers, polls state, and builds crash/debug packets.

3. Execution plane
   Actual work runs either:
   - remotely through HPC shell and Slurm wrappers
   - locally through long-running worker processes
   - in sibling repos such as `/home/ub/code/fran`

## Canonical Paths
### Remote HPC path
Entrypoints under `/home/ub/code/agent/agent/hpc/cli/` submit or poll remote work.

Canonical submit+poll path:
- `/home/ub/code/agent/agent/hpc/cli/hpc_submit_poll_fetch.sh`

Canonical log refresh path:
- `/home/ub/code/agent/agent/hpc/cli/hpc_poll_logs.sh`

Registry implementation:
- `/home/ub/code/agent/agent/hpc/tools/job_registry.py`

### Local orchestration path
Local long-running jobs are launched and tracked by:
- `/home/ub/code/agent/agent/control_plane/local_registry.py`

This path writes same job-level evidence shape as HPC where practical:
- registry row
- per-job directory
- stdout/stderr
- metadata files
- orchestration metadata

## Ownership Rules
- Request surface chooses path; it should not absorb job-state logic.
- Control plane owns identity, provenance, state transitions, and crash packet assembly.
- Execution plane owns doing work, not redefining orchestration contracts.
- Cross-repo callers in `agent` must adapt to upstream repo behavior, not reverse.

## Change Rules
When adding new workflow, define these before adding convenience wrappers:
- canonical entrypoint
- control-plane owner
- registry/provenance write path
- stdout/stderr location
- crash evidence path
- rollback or recovery action

If change does not alter one of those boundaries, it probably belongs in code or feature-specific README, not here.
