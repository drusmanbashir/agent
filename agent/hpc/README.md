# HPC

Minimal init note for HPC helpers.

`~/code/` repos shared with HPC are mirrors of Sinclair.
Sinclair copies are the source of truth; remote HPC code changes can be discarded in favor of Sinclair.

CLI inventory: see `FUNCTIONS.md`.

Environment refresh:
- `env_refresh.sh --check-only`
  - Preferred non-mutating check for critical package drift between local and the HPC `dl` env.
- `env_refresh.sh`
  - Preferred apply path. Updates HPC only when it is missing packages or behind the local versions.
- Default package set: `torch`, `torchvision`, `torchaudio`, `torchmetrics`, `lightning`, `monai`, `numpy`, `nibabel`.
- Package scope is explicit: only requested packages are compared and updated.
- Remote Python defaults to `/data/home/mpx588/.conda/envs/dl/bin/python` and can be overridden with `HPC_ENV_REFRESH_REMOTE_PYTHON`.

Interactive allocation default:
- `cli/interactive.sh` now defaults to `salloc --ntasks=1 --cpus-per-task=16 -t 1:0:0 --mem-per-cpu=8G`.
- For single-process Lightning training, prefer one task plus CPU threads. Explicit multi-task interactive allocations can trigger Slurm validation failures.

Dataset sync exceptions:
- Broad/default dataset sync runs skip sync-on-demand datasets matching `uls23_*`.
- Explicitly naming a matching dataset still runs it on demand.

Dashboard entrypoint:
- `python3 agent/hpc/cli/hpc_dashboard.py`
  - Local Tkinter UI over `/s/agent_rw/hpc_logs/job_registry.tsv`.
  - Splits Active vs Closed jobs and dispatches refresh/poll/open actions through existing shell helpers.
  - Shows a `Poll` column with the last recorded status poll time.
  - UI date/time display uses British format `DD/MM/YYYY HH:MM:SS`.
- `hdash start`
  - Preferred launcher. Starts a detached local web dashboard bound to `127.0.0.1`, then prints the live URL.
  - Also runs `job_registry.sh archive 14` before the service comes up.
- `hdash status`
  - Reports whether the local web dashboard service is running.
- `hdash url`
  - Prints the live localhost URL only.
- `hdash stop`
  - Stops the detached local web dashboard service.
- `hpc_dashboard ...`
  - Compatibility alias for `hdash`, kept to avoid breakage in existing shell usage.
- `python3 agent/hpc/cli/hpc_dashboard_web.py --state-dir /s/agent_rw/hpc_logs/dashboard_service --meta-file /s/agent_rw/hpc_logs/dashboard_service/service.meta`
  - Underlying stdlib web server used by `hdash`.
  - Binds to `127.0.0.1` by default and exposes Active/Closed tabs, a `POLL` column for last status poll time, refresh, poll-selected, poll-all-active, active-job-only cancel-selected, and per-job local log views.
  - Cancel uses `cli/hpc_ssh.sh` with absolute `/opt/slurm/bin/scancel`, then runs one canonical `cli/hpc_poll_logs.sh` poll to refresh registry/log state.
  - UI date/time display uses British format `DD/MM/YYYY HH:MM:SS`.

Train stack behavior: `run_name=none` initializes a new run. Any non-`none` run name targets or resumes an existing run.

Submit/poll default cadence:
- `cli/hpc_submit_poll_fetch.sh` submits, writes local job metadata, starts a detached local worker, and returns without waiting for full job completion.
- For CPU-only wrapper scripts, `cli/hpc_submit_poll_fetch.sh` now also maps downstream `-c/--cpus-per-task` into `sbatch --cpus-per-task=...`, matching the existing `-n/--num-processes` to `--ntasks` inference.
- `cli/hpc_resubmit.sh <job_id>` replays a prior `hpc_submit_poll_fetch.sh` submission from local `job.meta` provenance only.
- `cli/hpc_poll_worker.sh` is the per-job detached poller. It is the owner of default poll-schedule resolution through `cli/poll_schedule.py`.
- Both `cli/hpc_poll_worker.sh` and ad hoc `cli/hpc_poll_logs.sh` stamp `last_polled_at` in `job_registry.tsv`.
- `cli/job_registry.sh archive [days]` moves terminal rows older than `days` from the active registry into `job_registry.archive.tsv`.
- The helper emits minute intervals as `base**i` for `i=0..steps-1` with defaults `base=3`, `steps=5`, so the default minute schedule is `1 3 9 27 81`.
- The worker converts those minutes to seconds before polling and keeps reusing the last interval after the generated steps.
- `--poll-schedule "..."` still overrides the default helper output with an explicit second-based schedule, and the worker honors that persisted override.

CPU-only compute defaults:
- `cli/preproc.sh`, `cli/project_init.sh`, `cli/datasource.sh`, and `cli/datasource_update.sh` now default to `#SBATCH --cpus-per-task=16`.
- Those CPU wrappers accept `-c/--cpus-per-task` for submit-time override compatibility and derive `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` from `SLURM_CPUS_PER_TASK`.
- `cli/queue_project_init_preproc.sh` defaults both queued jobs to `--cpus-per-task=16` and accepts one `-c/--cpus-per-task` override that applies to both jobs.
- `cli/queue_chain.sh` now defaults queued jobs to `--cpus-per-task=16` and accepts `--cpus-per-task` to override all queued steps together.
