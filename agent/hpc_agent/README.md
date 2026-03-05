# HPC Agent

CLI helper for HPC dataset transfer with a simple menu:
- option 1: download data folder
- option 2: upload data folder

Default remote root for downloads/uploads:
- `/data/EECS-LITQ/fran_storage/datasets/xnat_shadow`
- default remote login: `mpx588@login.hpc.qmul.ac.uk`

## Install
```bash
cd agent/hpc_agent
pip install -e .
```

## Interactive menu
```bash
hpc-agent menu
```
Menu behavior:
- always uses login `mpx588@login.hpc.qmul.ac.uk`
- always uses remote root `/data/EECS-LITQ/fran_storage/datasets/xnat_shadow`
- asks for subfolder when downloading/uploading
- asks explicitly for local destination folder (download)
- asks explicitly for local folder path (upload)
- uses `rsync` only, and SSH will prompt for password

## Direct commands
Download:
```bash
hpc-agent download nodesthick /s/xnat_shadow/hpc --yes
```

Upload:
```bash
hpc-agent upload /local/folder --yes
```

Optional flags:
- `--remote mpx588@login.hpc.qmul.ac.uk` (default shown)
- `--remote-root <path>` (default is the fixed HPC root above)
- `--backup-root /tmp/hpc_agent_backups` local temp backup root for replaced files during download
- `--no-backup` disable local backup during download

## Fail-safe behavior for large downloads
- Download via `rsync` uses `-avz --partial`.
- If the target folder already exists locally, replaced files are moved to a timestamped backup directory under `/tmp/hpc_agent_backups` (configurable with `--backup-root`).
