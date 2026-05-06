# Registry Schema

## Purpose
This document defines durable job-tracking contract for `agent`. It covers registry row, per-job directory, and minimum provenance required for troubleshooting.

## Canonical Registry Files
Default root:
- `/s/agent_rw/hpc_logs/`

Primary files:
- `/s/agent_rw/hpc_logs/job_registry.tsv`
- `/s/agent_rw/hpc_logs/job_registry.archive.tsv`

Implementation:
- `/home/ub/code/agent/agent/hpc/tools/job_registry.py`

## Registry Row
Canonical TSV column order:

1. `job_id`
2. `submitted_at`
3. `sbatch_file`
4. `job_name`
5. `remote_script`
6. `state`
7. `exit_code`
8. `finished_at`
9. `last_polled_at`
10. `input_method`
11. `submit_argv`

## Per-Job Directory Contract
Each job owns directory at:
- `/s/agent_rw/hpc_logs/<job_id>/`

Expected artifacts:
- `std.out`
- `std.err`
- `job.meta`
- `worker.meta`
- `orch.json`
- `worker.log`
- `poll.log`

Not every path writes every file, but new orchestration flows should reuse this shape unless there is clear reason not to.

## Invariants
- `job_id` is stable join key across registry rows, logs, and metadata files.
- `submitted_at` is written once when job is created.
- `state`, `exit_code`, `finished_at`, and `last_polled_at` are mutable status fields.
- Terminal jobs are identified by terminal state prefixes or non-empty `finished_at`.
- `input_method` and `submit_argv` are provenance fields and should be preserved.
- Extra trailing columns may exist in legacy rows; readers must tolerate them.

## Compatibility Rules
- Additive metadata belongs in sidecar files before it belongs in new TSV columns.
- If new column is unavoidable, append it to right; do not reorder existing columns.
- Parsers should continue to normalize legacy rows rather than forcing whole-registry rewrites.
