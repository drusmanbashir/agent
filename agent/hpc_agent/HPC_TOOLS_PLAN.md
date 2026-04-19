# HPC Tools Suite Plan

Operator: `green` sub-agent.

Resource config: `green.resources.toml`.

HPC connection source: `$FRAN_CONF/hpc.yaml`.

## Current Tools

- `hpc-agent menu`: interactive transfer menu.
- `hpc-agent dashboard`: alias for `menu`.
- `hpc-agent download <dataset_folder> <local_dest>`: pull one dataset folder from the QMUL HPC XNAT shadow root with `rsync -avz --partial`.
- `hpc-agent upload <local_folder>`: push one local folder to the QMUL HPC XNAT shadow root with `rsync -avz --partial`.
- Download backup behavior: when the local target exists, replaced files can be backed up under the configured local backup root.

## Fixed Resources

- Remote login: derived from `username@host` in `$FRAN_CONF/hpc.yaml`.
- Dataset files: local paths are in `$FRAN_CONF/datasets.yaml` and mirroring hpc paths are in `$FRAN_CONF/datasets_hpc.yaml`.

- Username: loaded from `username`.
- Host: loaded from `host`.
- Password: loaded from `password`; never commit it.
- HPC storage: loaded from `hpc_storage`.
- HPC config path: loaded from `hpc_conf`.
- Remote XNAT shadow root: derived from the parent of `hpc_conf` plus `datasets/xnat_shadow`.
- Local backup root: loaded from `HPC_AGENT_BACKUP_ROOT` or tool default.

## Proposed Suite

1. `resources`
   - Print resolved operator config.
   - Redact secrets.
   - Verify required binaries: `ssh`, `rsync`, optional `sbatch`, `squeue`, `sacct`, `scancel`.

2. `ssh-check`
   - Test login derived from `$FRAN_CONF/hpc.yaml`.
   - Report auth method: key, agent, password prompt, or env-backed password helper.
   - No filesystem changes.

3. `ls-remote`
   - List folders below the config-derived XNAT shadow root.
   - Support `--depth`, `--pattern`, `--human`.

4. `download`
   - Existing command.
   - Add `--dry-run`, `--include`, `--exclude`, `--checksum`, `--delete` guarded by explicit confirmation.

5. `upload`
   - Existing command.
   - Add `--dry-run`, `--remote-subdir`, `--include`, `--exclude`, `--checksum`.
   - Require preflight summary before real upload.

6. `sync`
   - Bidirectional-safe wrapper around rsync.
   - Default mode: dry-run only.
   - Real mode requires direction: `local-to-hpc` or `hpc-to-local`.

7. `Dataset update`
   - mirroring: local and hpc datasets_hpc.yaml files should match in datasets except in parent folder. Regardless of parent of dataset on local machine, HPC datasets are always in ``"/data/EECS-LITQ/fran_storage/datasets/xnat_shadow/"`. Any changes made to datasets.yaml should be mirrored in dataset_hpc.yaml.
   - use dataset_config_load cli tool to upload dataset_hpc.yaml to hpc. Target path : (ON HPC, not local) $FRAN_CONF/dataset.yaml




9. `job-submit`
   - Submit Slurm jobs with `sbatch`.
   - Accept script path, job name, partition, time, memory, CPUs, GPUs, log path.
   - Print returned job ID.

10. `job-status`
    - Query `squeue` and `sacct`.
    - Show state, elapsed time, resources, exit code.

11. `job-cancel`
    - Cancel Slurm job with `scancel`.
    - Require confirmation unless `--yes`.

12. `logs`
    - Fetch or tail Slurm stdout/stderr paths.
    - Support `--job-id`, `--follow`, `--since`.

13. `disk`
    - Query remote disk usage with `du`, `df`, and quota command if available.
    - Output human-readable summary.

14. `manifest`
    - Build local or remote file manifest: path, size, mtime, optional checksum.
    - Compare manifests before/after transfer.

15. `xnat-shadow`
    - Higher-level dataset helpers for XNAT shadow folders.
    - Enforce matching rules only when upload/download task matches file metadata to subject IDs.

## Green Operating Rules

- Load `green.resources.toml` and `$FRAN_CONF/hpc.yaml` first.
- Merge ignored local secret overlay if present.
- Redact any password/token in logs.
- Use dry-run for transfer and destructive commands before real execution.
- Never delete remote data without explicit confirmation.
- Prefer SSH key/agent when available.
- If password is needed, call `hpc-agent load_pwd --field password --show-password`; never commit it.
