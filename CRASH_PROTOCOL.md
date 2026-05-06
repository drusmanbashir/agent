# Crash Protocol

## Purpose
This document defines minimum response loop for crashes in `agent`-managed workflows. It is for operational consistency, not postmortem narrative.

## Trigger
Use this protocol when:
- user reports crash
- agent detects crash in CLI or process execution
- tracked job ends in failed terminal state
- logs show orchestration state drift or missing evidence

## Evidence First
Identify failing boundary before changing code:

1. Request surface
   Wrong command mapping, bad wrapper assumptions, or invalid arguments.

2. Control plane
   Bad job creation, registry corruption, polling drift, missing provenance, or broken crash packet assembly.

3. Execution plane
   Real workload failed inside HPC, local worker, or upstream repo.

## Minimum Evidence Packet
For any tracked job, capture:
- `job_id`
- current registry row or equivalent status object
- `job.meta` when present
- `worker.meta` when present
- `orch.json` when present
- tail of `std.out`
- tail of `std.err`

Local crash packet builder:
- `/home/ub/code/agent/agent/control_plane/local_registry.py`

Registry implementation:
- `/home/ub/code/agent/agent/hpc/tools/job_registry.py`

## Response Rules
- Prefer smallest caller-side or control-plane fix that restores correctness.
- Do not change upstream sibling repos just to preserve stale `agent` contract.
- Preserve provenance and rollback visibility.
- Validate one normal path, one failure path, and one recovery or re-poll path.

## Recording
After crash fix, append entry to:
- `/home/ub/code/agent/agent/ts/CRASHLOG.md`

Minimum entry fields:
- crash type
- time
- fix implemented

## Non-Goals
This document does not define product behavior, feature policy, or full incident review format.
