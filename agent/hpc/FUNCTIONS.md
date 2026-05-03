# HPC Agent Script Inventory

## Folder: `cli/`

- `cli/hpc_ssh.sh [--login user@host] 'remote command'`
- `cli/hpc_ssh.sh [--login user@host] --script local_script.sh -- [args...]`
- `cli/hpc_ssh.sh --rsync [rsync args...]`
  - Shared SSH/rsync wrapper. Reads login/password from `$FRAN_CONF/hpc.yaml` via `tools.cli`.

- `cli/hpc_ssh_nopass.sh [--login user@host] 'remote command'`
- `cli/hpc_ssh_nopass.sh [--login user@host] --script local_script.sh -- [args...]`
- `cli/hpc_ssh_nopass.sh --rsync [rsync args...]`
  - Key-only SSH/rsync wrapper. Resolves login from `python -m tools.cli load_pwd --field login` (or `--login` override).
  - Enforces `BatchMode=yes` to avoid password prompts.
  - Defaults to `StrictHostKeyChecking=yes`; timeout controlled by `HPC_CONNECT_TIMEOUT` (default `8`).
  - On auth failure (`exit 255`), prints concise `ssh-keygen` / `ssh-copy-id` setup guidance.

- `cli/hpc_rsync.sh <rsync_args...>`
  - Pass-through to `hpc_ssh.sh --rsync`.

- `cli/interactive.sh [salloc args...]`
  - Opens an interactive SSH TTY to HPC and runs `salloc`.
  - Defaults to `salloc -n 16 -t 1:0:0 --mem-per-cpu=8G`.

- `cli/hpc_submit_poll_fetch.sh <local_sbatch_script> [script args...]`
  - Single supported submit+poll pathway.
  - Submit and poll, then fetch only that job's `.out/.err` into `/s/agent_rw/hpc_logs/<job_id>/`.
  - If script args include `-n <k>` or `--num-processes <k>`, submission also infers `sbatch --ntasks=<k>`.
  - If the completed job runtime exceeds 5 minutes, also copies the fetched logs to local `std.out`/`std.err` in that job folder and opens them in `nvim` when run interactively.
  - Also appends and updates `/s/agent_rw/hpc_logs/job_registry.tsv` with:
    - `job_id`, submission time, script path, job name, remote temp script
    - terminal `state`, `exit_code`, `finished_at` when polling returns completion/cancel/fail.

- `cli/hpc_poll_logs.sh [last|<job_id>]`
  - Canonical poll command for fetching and echoing stdout/stderr for an existing job.
  - Resolves `last` from `job_registry.tsv`; if registry is empty, falls back to newest job dir under `/s/agent_rw/hpc_logs`.
  - If local logs are missing in `/s/agent_rw/hpc_logs/<job_id>/`, downloads full files from HPC, then keeps canonical copies at:
    - `/s/agent_rw/hpc_logs/<job_id>/std.out`
    - `/s/agent_rw/hpc_logs/<job_id>/std.err`
  - Override destination root via `HPC_POLL_LOG_DEST`.
  - Echoes stdout first, then prompts whether to show stderr (`y/yes` only).

- All repo-managed Slurm submit paths under `cli/` and `tools/` append `job_registry.tsv` on submit.
  - `cli/hpc_submit_poll_fetch.sh` also updates terminal `state`, `exit_code`, and `finished_at` when polling completes.

- `cli/queue_project_init_preproc.sh [--login user@host] <project_title> <mnemonic> <plan_num> <datasource...> [-n <num_processes>]`
  - Queues paired project-init and dependent preproc jobs.
  - Uses the same `-n` value for both Slurm `ntasks` and downstream Python `-n`.
  - Appends both returned Slurm job IDs to the registry at submit time.

- `cli/queue_chain.sh [queue_chain args...]`
  - Queues dependent Slurm jobs via `tools/queue_chain.py`.
  - Appends each returned Slurm job ID to the registry at submit time.

- `cli/poll_active_jobs.sh [username]`
  - Poll active Slurm jobs using `squeue`.
  - If username omitted, uses the configured HPC username.

- `cli/job_registry.sh add <job_id> <submitted_at> <sbatch_file> <job_name> <remote_script>`
  - Append one submitted job row to the registry.
  - No-op if that `job_id` is already present.

- `cli/job_registry.sh submit <job_id> <sbatch_file> <job_name> <remote_script> [submitted_at]`
  - Convenience wrapper that timestamps and appends one submitted job row to the registry.
  - Repeated submit for the same `job_id` is idempotent.

- `cli/job_registry.sh finish <job_id> <final_state> <final_exit> <finished_at>`
  - Update terminal fields for an existing job row.

- `cli/job_registry.sh show last|yesterday|all`
  - Show registry rows by selector.

- `cli/job_registry.sh find <job_id>`
  - Show registry row for one specific job ID.

- `cli/job_registry.sh ids last|yesterday|all`
  - Print only job IDs by selector.

- `cli/job_registry.sh jobstats last|yesterday|all`
  - Run remote `jobstats -j <job_id> -l` for selected IDs.

- `cli/job_registry.sh path`
  - Print active registry file path.
  - Default path: `/s/agent_rw/hpc_logs/job_registry.tsv`

### Registry TSV Schema

- File: `/s/agent_rw/hpc_logs/job_registry.tsv`
- Delimiter: tab (`\t`)
- Column order:
  1. `job_id`
  2. `submitted_at`
  3. `sbatch_file`
  4. `job_name`
  5. `remote_script`
  6. `state`
  7. `exit_code`
  8. `finished_at`

- `cli/preproc.sh <t> <p> [-n <num_processes>]`
  - Slurm preprocess payload: `analyze_resample.py -t <t> -p <p> -n <num_processes>`.
  - Default `num_processes` is `1`.
  - Emits timestamped failure context to stderr (`failed_cmd`, `exit_code`) via `ERR` trap.

- FRAN-owned project shell CLIs
  - Use `fran/fran/run/project/project.sh` for project creation tasks.
  - Use `fran/fran/run/project/project_delete.sh` for project deletion tasks.
  - `agent/hpc/cli` no longer carries duplicate wrappers for these paths.

- `cli/project_edit -t <project_title> --add-datasource <ds> [-n <num_processes>]`
  - Repo-local project editor for existing FRAN projects.
  - Adds only missing datasources via `Project.add_data(...)`, then runs `maybe_store_projectwide_properties(overwrite=False)`.

- `cli/project_delete_all.sh <t1> [t2 ...]`
  - Slurm payload that loops project deletes.

- `cli/datasource.sh <f> <m> [-n <num_processes>]`
  - Slurm datasource-init payload: `datasource_init.py <f> <m> -n <num_processes>`.
  - Default `num_processes` is `1`.

- `cli/datasource_update.sh <f> <m> [-n <num_processes>] [--dry-run] [--return-voxels]`
  - Slurm datasource-update payload.
  - Default `num_processes` is `1`.

- `cli/update_datasources [dataset_name ...] [-n <num_processes>] [--dry-run] [--return-voxels]`
  - HPC wrapper for `fran/run/dataregistry/update_datasources.py`.
  - Reads `$FRAN_CONF/datasets.yaml` on HPC; if no dataset names are supplied, processes every dataset in the config.
  - Calls `Datasource.update_datasource(...)` per dataset, so missing `fg_voxels.h5` is initialized and existing h5 files are incrementally updated.

- `cli/train.sh <t> <p> <f> <l> <i> <v> <r>`
  - Slurm GPU training payload (`train_retry.py`).

- `cli/local_train.sh <t> <p> <f> <l> <i> <v> <r>`
  - Local training payload (`train.py`).

- `cli/git_all.sh [branch]`
  - Reset all git repos under `$COLD_STORAGE/code` to `origin/<branch>` (skips `ITK`).
  - `--mode pull` switches to `git pull --ff-only origin/<branch>` for safer refresh flows.
  - `--cold-storage /abs/path` sets the remote storage root explicitly.

- `cli/refresh.sh [dataset_name ...]`
  - Refreshes HPC state end-to-end.
  - Stage 0: sync local repos used on HPC before touching remote state.
  - Local repos covered: `fran`, `localiser`, `utilz`, `label_analysis`.
  - For each existing local git repo, runs `git add -A`, commits if dirty, then `git push -u origin <current-branch>`.
  - Stage 1: run `git_all.sh` on HPC using remote cold-storage resolved from local `$COLD_STORAGE` via local->HPC mapping.
  - This stage force-mirrors each repo to `origin/<branch>` with hard reset + clean, even if the remote repo is dirty.
  - Stage 2: refresh stale remote conf files via staged upload + remote rename:
    `datasets_hpc.yaml -> datasets.yaml`, `config_hpc.yaml -> config.yaml`, `best_runs.yaml -> best_runs.yaml`.
  - Stage 3: refresh `fran/run/project/project_status.py` onto HPC if stale.
  - Stage 4: sync dataset trees using local `$COLD_STORAGE/conf/datasets.yaml` vs remote `$COLD_STORAGE/conf/datasets.yaml`.
  - Dataset sync scope is limited to `images/` and `lms/`.
  - Each dataset prints a clear per-dataset diff plan before mutation.
  - Plan output classifies changes as `MISSING_REMOTE`, `STALE_REMOTE_OLDER`, `EXTRA_NOT_LOCAL`, and `REMOTE_NEWER_KEEP`.
  - Live dataset sync asks explicit `y/n` confirmation per dataset before upload/overwrite or remote-extra backup moves.
  - If confirmation is `n`, that dataset is skipped without remote mutation.
  - Remote extras (`EXTRA_NOT_LOCAL`) are moved to `$COLD_STORAGE/datasets/archived/<dataset_name>/<timestamp>/{images|lms}/...` and echoed before move.
  - Supports `--dry-run`, `--yes`, `--branch`, and optional dataset-name filters.

- `cli/git_hard_reset.sh [branch]`
  - Reset current repo to `origin/<branch>` and clean untracked files.

## Folder: `hpc_utils/`

- `hpc_utils/upload.sh`
  - Hardcoded rsync push helper for lits patches.

- `hpc_utils/main.py -t <project_title>`
  - Rewrites `bboxes_info` filename paths in project fixed-spacing folders.

## Python CLI Modules

- `tools/cli.py`
  - Main CLI for config loading, ssh credential fields, upload/download flows.

- `tools/datasets.py`
  - Dataset upload/update/poll utilities using config mappings.

- `tools/code.py`
  - Code-side helper module used by this package.

- `tools/refresh.py`
  - Python CLI behind `cli/refresh.sh`.
