Append instructions from /home/ub/code/AGENTS.md before the repo-specific instructions below if that file exists.

# AGENTS.md

## Session Start Behavior (Required)
- In the first assistant reply of a new workspace session, state the active folder path.
- Also mention a brief history of the last main task from the previous session.

## Permissions
for the below you do not need to ask explicit permission in completing tasks assigned by me:
 - you have my permission to read my code git repos, all past braches.
 - reading any files in ~/code or /s/ directories
 - reading and writing to /s/agent_rw/ subfolders. Full permissions given here

  ### Local Inspection Permissions
  You have my permission to run common non-destructive local inspection commands
  without asking me first, including:
  - `ps`, `pgrep`, `top -b -n 1`
  - `ls`, `find`, `rg`, `cat`, `sed`, `awk`, `head`, `tail`, `wc`
  - `git status`, `git log`, `git diff`, `git show`, `git branch`
  - reading `~/.codex/history.jsonl` for required startup context
  - reading files under `~/code`, `/s`, and the current workspace

  ### Escalation Preference
  If sandbox restrictions block non-destructive local inspection needed to
  answer my request, proceed by requesting escalated execution for the specific
  command without asking me first in chat.

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
- Git is the sole backup space.
- Do not create separate temporary backup copies unless I explicitly ask for them.


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
- use `sshpass` for HPC `rsync` commands by default
- Before executing any `rsync` command for an HPC transfer, show the exact command in chat and wait for explicit user approval before running it.

## Editing my code
### Coding Rules (Required)
1. Scope obedience
 - Implement only the stated change.
 - remember, you (CODEX) are a badly engineered program, your job is to right as few lines as possible to get the outcome so that i have to troubleshoot fewer lines when bugs appears as they ALWAYS do.
 - however, do not chain multiple commands to lower code count, code must remain readable. fewer lines should not occur by compressing multiple loops and variables assignments into a single line, but using FEWER instructions, fewer syntax checks and guards. gnerally assume i wil pass the correct arguments to my functions
 - If I say “the only diff is”, “just”, “only”, or “keep the rest the same”, treat that as a hard scope constraint.
 - Do not add abstraction, fallback handling, helper layers, renames, cleanup, or adjacent refactors unless I explicitly ask for them.
 - For a small refactor, copy the existing pattern and change only the explicitly named part.
2. Minimalism
 - I prefer fewest lines of code needed to achieve the result. Use that as much as possible.
 - When I ask for an outline or function sketch, produce the smallest working shape only.
 - Do not infer extra requirements from “best practice”.
 - Before adding any non-essential line, ask: does this directly satisfy my request?
3. No unnecessary defensive code
 - Do not add validation, prompts, fallback logic, backups, or helper abstractions unless I explicitly ask for them.
 - For a single-user local workflow, do not add multi-user, portability, or defensive abstractions unless I explicitly ask for them.
 - If I ask for minimal argparse, use only the arguments necessary for the task and no convenience options.
4. Keep code direct
 - Prefer direct field access and direct returns over wrapper helper functions when possible.
 - Do not add path normalization unless I explicitly ask for it.
 - Do not use `expanduser()`, `resolve()`, `absolute()`, or similar path-cleanup helpers unless I explicitly ask for them.
 - For CLI Python files, define the `argparse` parser under the `if __name__ == "__main__":` block, following the pattern used in `fran/run/analyze_resample.py`.
 - Avoid list comprehensions when a simple loop will do. Prefer explicit loops.
 - Avoid variable names that also work as debugger commands or debugger shorthands.
 - Avoid nested assignments and avoid combining multiple commands or transformations into a single statement when separate lines are clearer.
5. Alpha cleanup mode
 - Treat all code as alpha, straight to the point, and not production-grade unless I explicitly ask otherwise.
 - Remove fallback branches, compatibility paths, portability code, and generic reuse that do not serve the active path.
 - Assume a single-user workflow unless I explicitly ask otherwise. Remove multi-user, cross-environment, and defensive compatibility code.
 - Prefer direct indexing and direct assumptions over compatibility guards. If the active path expects one structure, code only for that structure.
 - Remove unused options, feature flags, optional behaviors, and type/shape handling that are not used by the active path.
 - When simplifying, keep only the shortest readable path that serves the current codebase. Do not preserve `production-version` scaffolding unless I explicitly ask for it.
6. Registration behavior
 - When I say `register` a datasource, registration must be interactive.
 - Ask me for the registration key/name interactively if needed.
 - Ask me for an optional alias interactively.
 - Do not silently infer alias values when registering unless I explicitly ask for that.
 - Do not write registry entries non-interactively by default.
 - For registration workflows, prefer a short interactive prompt over extra CLI arguments.
7. Boundaries
 - Never alter or remove my section after if __name__ == '__main__':, unless they are breaking your code (like you want to put a script there), in which case, put a sys exit before the code reaches my block, and offer to remove it.
 - you do not edit my existing code without explicit permission from me.
 - you may freely edit files created by yourself without asking for permission. you identify such files by leaving your signature in a comment at topl
 - dict items should be simple values or variables, not composite code expressions

 ### Bugs
  - Only report a point as a bug if I can tie it to the active code path and show a concrete failure mode from the current implementation.
  - If it is only hypothetical brittleness, omit it unless you explicitly ask for hardening review.
  - When you ask for bugs, prioritize:
      - incorrect outputs
      - wrong aggregation/misaligned pairing
      - crashes on active paths
      - silent data corruption
  - Do not include “could break if X changed later” unless I label it explicitly as non-bug and you asked for that class of issue.

 - whenever retrieving dict keys do not use get(), directly index the dict with key name and let it throw exception if it fails

## Fran
### Inference
- Image-folder lookup file (use first when asked to run inference on a dataset):
  `/s/fran_storage/inference_image_folders.yaml`
- Dataset-root registry (resolve DS aliases like `lidc`, `curvaspdac`, `colonmsd10`):
  `/s/fran_storage/conf/datasets.yaml`
- Best-runs registry:
  `/s/fran_storage/conf/best_runs.yaml`
- LIDC convention:
  treat `LIDC-0010` as the current best active run unless the user says otherwise; ask for confirmation before launching long inference jobs.

- Inference categories and when to use them:
  1. Base: sliding-window inference over a full preprocessed image. Use when `plan_train.mode == "source"`.
  2. Whole: single-pass patch inference on an image resized to patch size. Use when `plan_train.mode == "whole"`.
  3. Cascade: first localise ROI with whole/base localiser, then run patch inferer on cropped region. Typically used when mode is `"lbd"` (or patch-like runs).

- If a user request contains `inference`, `predict`, `prediction`, or close variants, use `/home/ub/code/fran/fran/run/predict.py` by default.
- Required user inputs: `project title` and `input images folder`.
- Optional user input: `--gpus` list; default to `[0]` if omitted.
- Resolve `run_w`, `run_p`, and `localiser_labels` from `/s/fran_storage/conf/best_runs.yaml` using the project title key.
- Do not set a custom output directory; always use the project predictions folder resolved by FRAN.
- Canonical command shape:
  `python /home/ub/code/fran/fran/run/predict.py -t <project_title> --run-w <run_w> --run-p <run_p> --localiser-labels <labels...> -i <images_folder> [--gpus <ids...>] [--chunksize 5] [--overwrite]`

## Common File Locations And Purposes
- `/s/fran_storage/conf/datasets.yaml`: canonical dataset aliases and root folders.
- `/s/fran_storage/conf/best_runs.yaml`: curated best runs for non-LIDC projects.
- `/s/fran_storage/inference_image_folders.yaml`: quick lookup for common inference image folders.
- `/home/ub/code/fran/fran/inference/base.py`: Base inferer (`source` mode, sliding-window).
- `/home/ub/code/fran/fran/inference/cascade.py`: Whole and Cascade inferers (`whole`, `lbd` flows).
- `/home/ub/code/fran/fran/inference/ensemble.py`: multi-run inference orchestration.
