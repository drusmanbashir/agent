# Agent Call Graph

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
