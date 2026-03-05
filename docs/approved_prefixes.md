# Approved Prefixes (Session Reference)

This file tracks the command prefixes approved during this workspace session for ULS23 dataset work.

Note: Enforcement is runtime-managed by the agent host; this file is a human-readable reference, not the source of truth.

## Download and metadata

- `curl -sL https://zenodo.org/api/records/10035161`
- `curl -sL https://zenodo.org/api/records/?q=ULS23&size=20`
- `wget -c --content-disposition`
- `wget -S --spider`

## Background jobs

- `nohup bash -lc`
- `setsid -f bash -lc`

## Environment/package setup used for extraction

- `/home/ub/mambaforge/bin/mamba install -n dl -y -c conda-forge p7zip`

## Practical tip

If you want fewer prompts in future runs, approve generic but scoped prefixes for trusted domains/tools, then I can reuse those patterns directly.
