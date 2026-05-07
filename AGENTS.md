# AGENTS.md



### Defaults
- `HPC_DEFAULT_DOWNLOAD_SRC=/s/agent_rw/`
- `HPC_DEFAULT_UPLOAD_DEST=$COLD_STORAGE@hpc`

## Architecture Anchors
- Use `/home/ub/code/agent/ORCHESTRATION.md` for canonical execution paths, layer boundaries, and ownership.
- Use `/home/ub/code/agent/REGISTRY_SCHEMA.md` for job registry columns, per-job artifacts, and compatibility rules.
- Use `/home/ub/code/agent/CRASH_PROTOCOL.md` for crash triage flow, minimum evidence, and CRASHLOG expectations.
- Treat these docs as first-stop architecture source. Keep reusable structure there; keep task-specific operating rules in this file.

## CRASHLOG Policy
- Maintain an append-only `CRASHLOG` in `/home/ub/code/agent/agent/ts/`.
- Add a new entry after each crash fix when:
  - the user reports a crash, or
  - the agent detects a crash in CLI/process execution.
- Each entry must record:
  - crash type (concise statement)
  - time
  - fix implemented

## Upstream Caller Policy
- Hard rule: agent-side helper scripts in `~/code/agent` are subservient to library/app methods in sibling repos under `~/code/...` that they call.
- Do not change upstream called methods/classes to fit agent scripts.
- Change the agent script/caller to fit the upstream API/behavior.
- If a called upstream method drifts significantly from the script signature/contract, prefer rewriting the entire agent-side script from scratch when that preserves readability and keeps code count low.

## HPC
HPC refers to a remote computer in Queen Mary Uni, I ssh into, to run deep learning scripts. Relevant phrases:
when i use the word folder/directory with phrases like "cold +/- storage", "checkpoint(s)", "rapid_access", "ray", look in:
Local folders /s/fran_storage/conf/config.yaml, remote (HPC): /s/fran_storage/conf/config_hpc.yaml
- for hpc related commands resolve my intent by reading agent/hpc/README.md


- Expansion rule for script:
  - `agent/hpc/cli/hpc_xfer.sh` resolves `@hpc` to the login from `$FRAN_CONF/hpc.yaml` when available.
  - `$COLD_STORAGE@hpc` expands to the remote `cold_storage_folder` from `$FRAN_CONF/config_hpc.yaml` when available.
  - fallback: if no remote cold-storage mapping is available, use `$COLD_STORAGE` with the resolved HPC login.

### Intent -> Command Mapping
- `hpc download [dest]` -> `agent/hpc/cli/hpc_xfer.sh download <dest_local>` (source defaults to `/s/agent_rw/` on HPC)
- `hpc download [src] [dest]` -> `agent/hpc/cli/hpc_xfer.sh download <src_remote> <dest_local>`
- `hpc upload [src]` -> `agent/hpc/cli/hpc_xfer.sh upload <src_local>` (destination defaults to expanded `$COLD_STORAGE@hpc`)
- `hpc upload [src] [dest]` -> `agent/hpc/cli/hpc_xfer.sh upload <src_local> <dest_remote>`
- `hpc submit/poll <sbatch> [args...]` -> `agent/hpc/cli/hpc_submit_poll_fetch.sh <local_sbatch_script> [script args...]`
  - This is the only allowed submit+poll path; it must write `job_registry.tsv`.
- Canonical poll path for log retrieval and echo:
  - `hpc poll logs [last|job_id]` -> `agent/hpc/cli/hpc_poll_logs.sh [last|job_id]`
  - Keyword variants map to this same canonical poll command:
    - `hpc retrieve std.out/std.err [last|job_id]`
    - `hpc fetch stdout stderr [last|job_id]`
  - Behavior: fetches full stdout/stderr files if missing locally, copies them to `/s/agent_rw/hpc_logs/<job_id>/` (`HPC_POLL_LOG_DEST` override), echoes stdout first, then prompts to echo stderr on `y/yes`.
- `hpc existing tools check` -> `rg -n "download|upload|rsync" agent/hpc scripts`

### HPC Execution Policy
- `--dry-run` is for validation/debug only.
- Once a function/path has been validated and cleared, do real execution by default (no `--dry-run` flag).
- If uncertain, run one dry-run once, then remove `--dry-run` for the actual run.
- For `agent/hpc/cli/hpc_ssh.sh`, do not send inline Python here-docs or long Python command strings to fulfill requests.
- When remote helper logic is needed, use an existing checked-in script or upload an existing local script file with `--script`, and prefer rsync for moving missing files.
- Do not create or upload a new helper script for HPC work unless the user explicitly approves it first.
- If the required HPC logic does not already exist in checked-in scripts/commands, state that clearly, stop, and ask for permission before creating a new script.

## XNAT Ruleset (Required)
- For any XNAT upload/download task that matches file metadata to subject IDs, load and follow:
  `automation/xnat/workflows/matching_rules.v1.yaml`
- Enforce this ruleset before matching begins.
- Matching parser is fixed to `info_from_filename` from `~/code/utilz/utilz/helpers.py`.
- Before any XNAT upload action, show a preflight sample of 1 to 3 files in chat:
  filename, parsed `(project, subject_id, date, description)`, and planned action.
- Before any XNAT upload action, explicitly ask:
  create new subject if missing, or skip missing subjects.
- Before any XNAT download action, show a preflight sample of 1 to 3 items in chat:
  planned project/subject/label targets and destination path.

## External Utility Paths
- For filename metadata parsing, use `info_from_filename` from `~/code/utilz/utilz/helpers.py`.
- The function is imported in that file via `utilz.stringz`, but this `helpers.py` path is the default lookup path for this workspace.
- When matching SITK LM and image datasets, compare only `(project, subject_id, date)` derived from that function.

## General File Handling (Required)
- Before any file delete or overwrite operation, create a temporary backup copy first.
- Default temporary backup root: `$CODEX_HOME/agent_file_backups/<timestamp>`.
- Apply this rule to all datasets and automation tasks unless the user explicitly opts out.
- Every backup batch must include a `manifest.tsv` with at least:
  `original_path`, `backup_path`, `operation`, `timestamp`.
- Backup filenames must preserve original basenames so files can be restored in-place.

## Dataset Creation And Curation Rules (Required)
- For any imaging dataset creation/curation/download task, enforce:
  `automation/datasets/imaging_dataset_creation_curation_rules.v1.yaml`
- Default dataset root is fixed to: `/s/agent_rw/datasets`
- Required per-dataset output folders:
  `images/` for image volumes and `lms/` for labelmaps/segmentations.
- Keep basename parity after conversion/normalization:
  if image is `images/<name>.nii.gz`, labelmap must be `lms/<name>.nii.gz`.
- filenames usually follow the pattern of <project>_<case_id>_<suffix>.nii.gz , <project> must always match the name of the parent folder containing images/ and lms/, case_id is numeric and is usually given either in the filename itself or if each case is in a unique folder, the folder itself has a numeric name.
- Preserve original source artifacts under `<dataset>/_source/` and write audit logs under `<dataset>/_logs/`.

## For any request to push to HPC, andrena:
- use the agent/hpc_agent/ for further instructions

## Editing my code
- All code in my repos is for personal use only, not for public. So code is minimalist. Do not introduce type checks and failsafes. If an attribute is supposed to exist when you call it, I'd rather the code break with an exception than silently pass it over. Also if an integer is expected in a function argument, do not place checks to convert other types (str, float) to int. Let it break if I pass it a non-integer.
- You do not have permission to alter existing code, you have to ask for 'go' before you install your proposed edits. However, you may create / delete new files made entirely by you.
- You do not have permission to push / pull or any other git operations which change the code (you can do git status, for example) without asking for 'go'
- Never alter or remove my section after if __name__ == '__main__':, unless they are breaking your code (like you want to put a script there), in which case, put a sys exit before the code reaches my block, and offer to remove it.
