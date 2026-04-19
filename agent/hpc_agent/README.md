# HPC Agent Function Inventory

## Access Scripts

- `scripts/hpc_ssh.sh`
  - Password-aware SSH wrapper using `$FRAN_CONF/hpc.yaml`.
  - Direct command:
    ```bash
    scripts/hpc_ssh.sh 'hostname; pwd'
    ```
  - Run a local shell script on HPC over stdin:
    ```bash
    scripts/hpc_ssh.sh --script scripts/git_all.sh -- main
    ```
  - Optional login override:
    ```bash
    scripts/hpc_ssh.sh --login user@host 'hostname'
    ```

- `scripts/hpc_rsync.sh`
  - Password-aware `rsync` wrapper using the same SSH transport as `hpc_ssh.sh`.
  - Example:
    ```bash
    scripts/hpc_rsync.sh -avzn --list-only user@host:/remote/path/
    ```

## Operational Shell Scripts

- `scripts/git_all.sh`
  - On the machine where it runs, scans `$COLD_STORAGE/code` for Git repos.
  - Fetches, hard-resets, and cleans each repo to `origin/<branch>`.
  - Skips repos named `ITK`.

- `scripts/git_hard_reset.sh`
  - Git reset helper.

- `scripts/project.sh`
  - Project shell helper.

- `scripts/train.sh`
  - Training shell helper.

- `scripts/local_train.sh`
  - Local training shell helper.

## Python CLI: `tools/cli.py`

- `ConfigError`
  - Config/runtime error type for CLI failures.

- `_load_hpc_config(config_path=None)`
  - Loads `$FRAN_CONF/hpc.yaml`.
  - Produces `login`, `hpc_conf`, `hpc_storage`, `xnat_shadow_root`, and redaction-safe fields.

- `_run_download(...)`
  - Builds and runs one `rsync` download.

- `_run_upload(...)`
  - Builds and runs one `rsync` upload.

- `_run_load_pwd(...)`
  - Prints HPC config fields, redacting password unless explicitly requested.

- `main(argv=None)`
  - CLI entry point for:
    - `menu`
    - `dashboard`
    - `load_pwd`
    - `download`
    - `upload`

## Python Dataset Tools: `tools/datasets.py`

- `run_dataset_upload(dataset_names, remote, yes, config_path)`
  - Full dataset upload by dataset name.
  - Resolves local folder from `$FRAN_CONF/datasets.yaml`.
  - Resolves remote target from `$FRAN_CONF/datasets_hpc.yaml`.

- `update_dataset(dataset_names, remote, yes, config_path, dry_run=False)`
  - Delta update for dataset `images/` and `lms/`.
  - Uploads local files missing remotely or newer locally.
  - Deletes remote files missing locally after successful upload.
  - `dry_run=True` prints upload/delete plans only.

- `delete_files_on_remote(filenames)`
  - Deletes absolute remote file paths via `scripts/hpc_ssh.sh`.
  - Rejects invalid absolute paths.

- `poll_datasets(dataset_names, remote, config_path)`
  - Read-only local/remote dataset drift table.
  - Counts `images/` and `lms/`.
  - Reports `missing_remote`, `missing_local`, `remote_old`, `local_old`.

- `main(argv=None)`
  - CLI entry point:
    ```bash
    python -m tools.datasets --mode upload kits23
    python -m tools.datasets --mode update_dataset kits23 --dry-run
    python -m tools.datasets --mode poll_datasets kits23
    ```

## Python Utility: `hpc_utils/main.py`

- `fix_bboxes_filenames(bboxes_info, dest_hpc_folder)`
  - Rewrites bbox filename destinations for HPC.

- `main(args)`
  - Utility entry point.
