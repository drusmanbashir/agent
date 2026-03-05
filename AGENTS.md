# AGENTS.md

## Session Start Behavior (Required)
- In the first assistant reply of a new workspace session, state the active folder path.
- Also mention a brief history of the last main task from the previous session.

## Startup Consistency
- Treat these two bullets as mandatory startup checks for every new session in this workspace.
- If prior-session context is unclear, derive a one-line summary from `$CODEX_HOME/history.jsonl`.

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

k## For any request to push to HPC, andrena: 
- use the agent/hpc_agent/ for further instructions

## Editing my code
 - Never alter or remove my section after if __name__ == '__main__':, unless they are breaking your code (like you want to put a script there), in which case, put a sys exit before the code reaches my block, and offer to remove it.

