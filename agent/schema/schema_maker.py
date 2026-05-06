#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent

AGENT_MD = """# Agent Call Graph

Sample rule: agent-centered slice from the shared CLI sample; immediate edges only, with deeper HPC helper paths.

| Entry | Purpose | Immediate Calls |
| --- | --- | --- |
| `agent/hpc/cli/hpc_submit_poll_fetch.sh` | Submit, poll, fetch logs | `cli/poll_schedule.py`, `cli/hpc_ssh.sh`, `cli/hpc_rsync.sh`, `cli/job_registry.sh add/finish`, `remote sbatch` |
| `agent/hpc/cli/hpc_poll_logs.sh` | Resolve job, refresh, fetch logs | `cli/job_registry.sh ids/find`, `cli/hpc_ssh.sh`, `cli/hpc_rsync.sh` |
| `agent/hpc/cli/refresh.sh` | Refresh local and remote HPC state | `python -m tools.refresh`, `_sync_local_repos`, `git add/commit/push`, `_run/_remote_shell_cmd`, `cli/hpc_rsync.sh` |
| `agent/hpc/cli/train.sh` | Slurm wrapper for FRAN training | `fran/run/training/train_retry.py` |
| `scripts/fill_localiser_cache.py` | Backfill missing localiser cache JSONs | `stage missing images`, `CacheFillInferer`, `LocaliserInfererPT`, `inferer.run(...)` |

```mermaid
flowchart TD
  classDef file fill:#dbeafe,stroke:#1d4ed8,color:#0f172a,stroke-width:1.5px;
  classDef func fill:#dcfce7,stroke:#15803d,color:#0f172a,stroke-width:1.5px;
  classDef cmd fill:#ffedd5,stroke:#c2410c,color:#0f172a,stroke-width:1.5px;
  classDef step fill:#f3f4f6,stroke:#4b5563,color:#111827,stroke-width:1.5px;

  subgraph HPC[HPC wrappers]
    H1["agent/hpc/cli/hpc_submit_poll_fetch.sh"]:::file
    H1A["cli/poll_schedule.py"]:::file
    H1A1["emit minute schedule"]:::cmd
    H1B["cli/hpc_ssh.sh"]:::file
    H1B1["sequence<br/>1. mkdir remote temp<br/>2. submit bash -lc<br/>3. poll squeue/sacct"]:::step
    H1C["cli/hpc_rsync.sh"]:::file
    H1C1["sequence<br/>1. upload sbatch script<br/>2. fetch stdout/stderr"]:::step
    H1D["cli/job_registry.sh add/finish"]:::cmd
    H1E["remote sbatch"]:::cmd

    H1 --> H1A
    H1A --> H1A1
    H1 --> H1B
    H1B --> H1B1
    H1 --> H1C
    H1C --> H1C1
    H1 --> H1D
    H1 --> H1E

    H2["agent/hpc/cli/hpc_poll_logs.sh"]:::file
    H2A["cli/job_registry.sh ids/find"]:::cmd
    H2A1["sequence<br/>1. resolve last id<br/>2. find registry row"]:::step
    H2B["cli/hpc_ssh.sh"]:::file
    H2B1["sequence<br/>1. scontrol stdout/stderr<br/>2. sacct status<br/>3. squeue live state"]:::step
    H2C["cli/hpc_rsync.sh"]:::file
    H2C1["sequence<br/>1. refresh local logs<br/>2. fetch missing logs<br/>3. copy std.out/std.err"]:::step

    H2 --> H2A
    H2A --> H2A1
    H2 --> H2B
    H2B --> H2B1
    H2 --> H2C
    H2C --> H2C1

    H3["agent/hpc/cli/refresh.sh"]:::file
    H3A["python -m tools.refresh"]:::cmd
    H3B["sequence<br/>1. _sync_local_repos<br/>2. branch check<br/>3. git add/commit/push"]:::step
    H3B1["local repo sync"]:::cmd
    H3C["sequence<br/>1. _run/_remote_shell_cmd<br/>2. cli/hpc_rsync.sh<br/>3. remote repos/conf/datasets"]:::step
    H3C1["remote refresh"]:::cmd

    H3 --> H3A
    H3A --> H3B
    H3B --> H3B1
    H3A --> H3C
    H3C --> H3C1

    H4["agent/hpc/cli/train.sh"]:::file
    H4A["fran/run/training/train_retry.py"]:::file

    H4 --> H4A

  end

  subgraph HELPER[Agent helpers]
    S1["scripts/fill_localiser_cache.py"]:::file
    S1A["sequence<br/>1. stage missing images<br/>2. CacheFillInferer<br/>3. LocaliserInfererPT<br/>4. inferer.run(...)"]:::step

    S1 --> S1A

  end

  subgraph LEGEND[Legend]
    L1["script or module path"]:::file
    L2["method, constructor, or callable"]:::func
    L3["shell or remote command"]:::cmd
    L4["control-flow or staged sequence"]:::step
  end
```

## Notes

- HPC paths are taken one layer deeper than the rest of the sample.
- Sequence boxes enumerate ordered direct calls from one owner node.
- Cross-repo leaves stay compact when they point into FRAN.
"""

FRAN_MD = """# FRAN Call Graph

Sample rule: FRAN-centered slice from the shared CLI sample; immediate edges only, with sequence boxes for ordered manager flow.

| Entry | Purpose | Immediate Calls |
| --- | --- | --- |
| `fran/run/project/project.sh` | Thin project creation wrapper | `project_init.py` |
| `fran/run/project/project_init.py` | Create project and attach datasources | `DS.names()`, `Project(...)`, `Project.create(...)`, `Project.add_data(...)`, `Project.maybe_store_projectwide_properties(...)` |
| `fran/run/dataregistry/update_datasources.py` | Init or update datasource H5 state | `load_datasets()`, `Datasource(folder, name)`, `ds.update_datasource(...)` |
| `fran/run/preproc/analyze_resample.py` | Analyze, resample, emit mode datasets | `Project(...)`, `ConfigMaker(...)`, `confirm_plan_analyzed(...)`, `process_plan(args)`, `PreprocessingManager(args)`, `resample_dataset(...)`, `plan mode branch` |
| `fran/run/training/train_retry.py` | Retry training on CUDA OOM | `build train.py cmd`, `subprocess.Popen(...)`, `train.py`, `OOM marker check`, `reduced batch size retry` |

```mermaid
flowchart TD
  classDef file fill:#dbeafe,stroke:#1d4ed8,color:#0f172a,stroke-width:1.5px;
  classDef func fill:#dcfce7,stroke:#15803d,color:#0f172a,stroke-width:1.5px;
  classDef cmd fill:#ffedd5,stroke:#c2410c,color:#0f172a,stroke-width:1.5px;
  classDef step fill:#f3f4f6,stroke:#4b5563,color:#111827,stroke-width:1.5px;

  subgraph PROJECT[Project and data]
    F1["fran/run/project/project.sh"]:::file
    F1A["project_init.py"]:::file

    F1 --> F1A

    F2["fran/run/project/project_init.py"]:::file
    F2A["sequence<br/>1. DS.names()<br/>2. Project(project_title=...)<br/>3. Project.create(...)<br/>4. Project.add_data(...)<br/>5. Project.maybe_store_projectwide_properties(...)"]:::func

    F2 --> F2A

    F3["fran/run/dataregistry/update_datasources.py"]:::file
    F3A["sequence<br/>1. load_datasets()<br/>2. Datasource(folder, name)<br/>3. ds.update_datasource(...)"]:::func

    F3 --> F3A

  end

  subgraph PREPROC[Preproc]
    F4["fran/run/preproc/analyze_resample.py"]:::file
    F4A["sequence<br/>1. Project(...)<br/>2. ConfigMaker(...)<br/>3. confirm_plan_analyzed(...)<br/>4. process_plan(args)"]:::func
    F4B["sequence<br/>1. PreprocessingManager(args)<br/>2. resample_dataset(...)<br/>3. select plan mode"]:::step
    F4C["patch/pbd<br/>1. generate_hires_patches_dataset(...)"]:::step
    F4D["lbd<br/>1. generate_lbd_dataset(...)"]:::step
    F4E["imported lbd<br/>1. generate_TSlabelboundeddataset(...)"]:::step
    F4F["rbd<br/>1. generate_rbd_dataset(...)"]:::step
    F4G["whole<br/>1. generate_whole_images_dataset(...)"]:::step

    F4 --> F4A
    F4A --> F4B
    F4B --> F4C
    F4B --> F4D
    F4B --> F4E
    F4B --> F4F
    F4B --> F4G

  end

  subgraph TRAIN[Training]
    T1["fran/run/training/train_retry.py"]:::file
    T1A["sequence<br/>1. build train.py cmd<br/>2. run subprocess<br/>3. collect combined output"]:::step
    T1C["sequence<br/>1. inspect OOM markers<br/>2. reduce batch size<br/>3. next attempt"]:::step
    T1B["agent/hpc/cli/train.sh"]:::file

    T1 --> T1A
    T1A --> T1C
    T1B --> T1

  end

  subgraph LEGEND[Legend]
    L1["script or module path"]:::file
    L2["method, constructor, or callable"]:::func
    L3["shell or remote command"]:::cmd
    L4["control-flow or staged sequence"]:::step
  end
```

## Notes

- This view stays near the current depth except for analyze_resample.py and train_retry.py.
- Sequence boxes enumerate ordered direct calls from one owner node.
- Cross-repo leaves stay compact when they point back into agent wrappers.
"""

README_MD = """# Schema Graphs

| Schema | Markdown | SVG |
| --- | --- | --- |
| FRAN Call Graph | [FRAN_CALL_GRAPH.md](FRAN_CALL_GRAPH.md) | [FRAN_CALL_GRAPH.svg](FRAN_CALL_GRAPH.svg) |
"""

DOCS = {
    "agent": ("AGENT_CALL_GRAPH.md", AGENT_MD),
    "fran": ("FRAN_CALL_GRAPH.md", FRAN_MD),
}


def mermaid_block(markdown: str) -> str:
    return markdown.split("```mermaid\n", 1)[1].split("\n```", 1)[0]


def export_svg(markdown_name: str, markdown: str) -> None:
    mermaid = mermaid_block(markdown)
    svg_path = ROOT / markdown_name.replace(".md", ".svg")
    with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False) as mmd_file:
        mmd_file.write(mermaid)
        mmd_path = Path(mmd_file.name)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as cfg_file:
        cfg_file.write('{"args":["--no-sandbox","--disable-setuid-sandbox"]}')
        cfg_path = Path(cfg_file.name)
    subprocess.run(
        [
            "npx",
            "-y",
            "@mermaid-js/mermaid-cli",
            "-p",
            str(cfg_path),
            "-i",
            str(mmd_path),
            "-o",
            str(svg_path),
        ],
        check=True,
    )
    mmd_path.unlink()
    cfg_path.unlink()


def write_doc(markdown_name: str, markdown: str) -> None:
    (ROOT / markdown_name).write_text(markdown)
    export_svg(markdown_name, markdown)


def main() -> None:
    names = sys.argv[1:] if sys.argv[1:] else ["agent", "fran"]
    for name in names:
        markdown_name, markdown = DOCS[name]
        write_doc(markdown_name, markdown)
    (ROOT / "README.md").write_text(README_MD)


if __name__ == "__main__":
    main()
