# AGENTS.md

## HPC Log Reporting
- For any request that checks or summarizes job logs (local or remote), always include:
  - remote log path(s), and
  - local artifact path(s) under `/s/agent_rw/hpc_logs/<job_id>/` when they exist.
- If no local copy exists yet, state that explicitly and provide the exact command/path to create it.
- This requirement applies to subagent outputs too (including Goku): responses are incomplete unless local log location status is stated.
