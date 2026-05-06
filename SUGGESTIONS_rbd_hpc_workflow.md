# RBD/HPC Workflow Suggestions

## Goal

Reduce token use, cut repeated diagnosis, make local->HPC FRAN preproc flows safer.

## Skill Suggestions

- Add `fran-preproc` skill.
  - Bundle canonical steps for project init, global-properties repair, datasource update, plan-folder resolve, local smoke run, HPC submit/poll.
  - Include known failure signatures:
    - `Datasource <x> not found in df`
    - `KeyError: 'mean_dataset_clipped'`
    - CPU intent lost between `setup(device=...)` and later inferer construction
- Add `fran-dataset-short` skill.
  - Create `<dataset>_shortN` datasets from canonical source.
  - Update both local and HPC dataset registries.
  - Run datasource init/update and verify `fg_voxels.h5`.
- Add `fran-hpc-preproc` skill.
  - Wrap `refresh.sh`, dataset sync, `queue_project_init_preproc.sh`, `hpc_submit_poll_fetch.sh`, `hpc_poll_logs.sh`.
  - Carry explicit retry policy and known env checks.

## Agent Config Suggestions

- Add startup cache file for FRAN/Totalseg.
  - Store plan IDs, datasource aliases, ckpt paths, canonical folders, common failure fixes.
  - Avoid re-reading large config surfaces every run.
- Add per-repo op-boundary note.
  - `local smoke`
  - `HPC ready`
  - `unsafe to proceed`
  - Lets agent stop early when boundary mismatch found.
- Add persistent shorthand map for high-use commands.
  - Example: `fran proj-init`, `fran preproc`, `fran gp-fix`, `fran ds-short`, `fran hpc-preproc`.

## CLI Suggestions

- Add `fran/run/project/project_bootstrap.py`.
  - Create/update project.
  - Verify datasource rows exist.
  - Repair missing `global_properties` fields by calling `maybe_store_projectwide_properties`.
  - Exit nonzero if bootstrap incomplete.
- Add `fran/run/preproc/preproc_smoke.py`.
  - Run one plan on few cases.
  - Emit stage timings.
  - Abort if localiser/YOLO pace crosses configured threshold.
- Add `agent/hpc/cli/project_bootstrap_poll.sh`.
  - Poll bootstrap/preproc job state using canonical registry/log path.
  - Print short diagnosis only.
- Add `agent/hpc/cli/dataset_short_create.sh`.
  - Build `*_shortN` folder from first/selected cases.
  - Sync paired `images/` and `lms/`.
  - Optionally register dataset in both YAML files.

## Spec / Rules Suggestions

- In AGENTS/skill spec, define datasource alias hazard explicitly.
  - If project mnemonic plan expects datasource `totalseg`, reject `drli_short` early unless alias/remapping contract says valid.
- Add rule: never kill `project_init.py` before `mean_dataset_clipped` exists.
- Add rule: local smoke should use `python -u` for long FRAN jobs to avoid silent buffered runs.
- Add rule: if process started by agent emits no output for `N` seconds, inspect filesystem progress before assuming hang.

## Token-Saving Suggestions

- Put known error -> fix map in one checked-in markdown or YAML.
  - Agent can search one small file instead of broad repo grep.
- Maintain one tiny rolling ops log template with fixed fields:
  - boundary
  - command
  - result
  - blocker
  - next
- Prefer small helper CLIs over repeated one-off Python snippets once command pattern repeats twice.
- Current `hpc_xfer` repo-sync path over-copies `.git`/cache/artifact trees; future helper should support an rsync exclude list or a clean mirror mode for shared repos.

## Tonight Hurdles

- `drli_short` is not drop-in valid for `totalseg` plan7.
  - Plan remapping expects datasource `totalseg`; project rows resolved to `drli`.
  - Future skill/spec should reject this boundary early, before long preproc attempts.
- Killing `project_init.py` early can leave `global_properties.json` half-populated.
  - Symptom: `KeyError: 'mean_dataset_clipped'` at resample setup.
  - Future helper should verify required keys after project bootstrap.
- For long FRAN CLIs, buffered stdout hides stage state.
  - `python -u` materially improves operability and token efficiency because fewer side checks are needed.
- Fallback success still emits inner `CropByYolo` mismatch log line to stdout/stderr.
  - Audit file is correct, but console noise may mislead operators.
  - Future tweak: downgrade/suppress inner warning when fallback later proves `verified_fg_preserved=True`.
- Mnemonic/plan-family contract must stay separate from project title.
  - Tmp title can vary.
  - Break happens when mnemonic plan family and datasource alias do not satisfy spreadsheet `datasources` contract.
