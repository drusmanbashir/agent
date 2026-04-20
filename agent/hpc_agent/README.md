# HPC Agent Function Inventory

## Access Scripts

- `scripts/hpc_ssh.sh [--login user@host] [--script local_script.sh -- [args...]] [--rsync ...] [remote command]`: SSH/rsync wrapper that reads `$FRAN_CONF/hpc.yaml` and applies shared HPC env overrides.
- `scripts/hpc_rsync.sh <rsync_args...>`: passes rsync args directly to `scripts/hpc_ssh.sh --rsync`.

## Operational Shell Scripts

- `scripts/git_all.sh [branch=main]`: scans `$COLD_STORAGE/code` repos and fetch/reset/clean to `origin/<branch>` (skips repo `ITK`).
- `scripts/git_hard_reset.sh [branch=main]`: hard-resets the current repo to `origin/<branch>` and removes untracked files.
- `scripts/project.sh [-t title] [-m mnemonic] [-ds ds1 ds2 ...] [-n workers] [title mnemonic datasource workers]`: `sbatch` wrapper for project creation via `project_init.py`.
- `scripts/project_delete.sh [-t|--project-title|--title|--project title] [title]`: `sbatch` wrapper for deleting one FRAN project via `project_delete.py -t`.
- `scripts/project_delete_all.sh [--projects title ...] [-t title ...] [title ...]`: `sbatch` wrapper for deleting multiple FRAN projects sequentially.
- `scripts/preproc.sh [-t title] [-p plan] [-n workers] [title plan workers]`: `sbatch` wrapper for preprocessing via `analyze_resample.py`.
- `scripts/hpc_sbatch.sh <local_sbatch_script> [script args...]`: copies a local batch script to remote, submits with `sbatch --parsable`, polls with `squeue`, and reports terminal state via `sacct` when available.
- `scripts/train.sh [project_title] [plan] [fold] [lr] [train_indices] [val_every_n_epochs] [run_name]`: Slurm GPU training launcher calling `train_retry.py`.
- `scripts/local_train.sh [project_title] [plan] [fold] [lr] [train_indices] [val_every_n_epochs] [run_name]`: local training launcher calling `train.py`.

## Python CLI: `tools/cli.py`

- `ConfigError`: exception type for CLI config/runtime failures.
- `_load_hpc_config(config_path=None)`: loads `hpc.yaml` and returns login/storage/conf fields plus derived transfer paths.
- `_run_download(remote, dataset_folder, local_dest, remote_root, backup_root, with_backup, yes)`: executes one download workflow using rsync.
- `_run_upload(remote, local_folder, remote_root, remote_subdir, yes)`: executes one upload workflow using rsync.
- `_run_load_pwd(config_path, field, show_password, output_format)`: prints selected config field(s) with password-redaction controls.
- `main(argv=None)`: CLI entry point for `menu`, `dashboard`, `load_pwd`, `download`, and `upload`.

## Python Dataset Tools: `tools/datasets.py`

- `run_dataset_upload(dataset_names, remote, yes, config_path)`: uploads named datasets using local and remote dataset mappings.
- `update_dataset(dataset_names, remote, yes, config_path, dry_run=False)`: syncs `images/` and `lms/` deltas (upload new/newer local, delete remote-only, or plan-only with `dry_run`).
- `delete_files_on_remote(filenames)`: validates absolute remote file paths then deletes them via the HPC SSH wrapper.
- `poll_datasets(dataset_names, remote, config_path)`: reports local/remote drift counts for `images/` and `lms/` files.
- `main(argv=None)`: CLI entry with `--mode upload|update_dataset|poll_datasets` and dataset name inputs.

## Python Utility: `hpc_utils/main.py`

- `fix_bboxes_filenames(bboxes_info, dest_hpc_folder)`: rewrites each bbox record filename from source-root paths to `dest_hpc_folder` paths.
- `main(args)`: takes `-t` project title, walks project fixed-spacing subfolders, and rewrites stored `bboxes_info` filename paths.
