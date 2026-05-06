Control-plane thin slice for FRAN datasource/project readiness.

Run instructions:
- Launcher: `/home/ub/code/agent/agent/control_plane/cli/acp`
- MCP stdio server via launcher: `/home/ub/code/agent/agent/control_plane/cli/acp stdio`
- MCP stdio server direct: `python -m agent.control_plane.mcp_server`
- Web UI: `uvicorn agent.control_plane.web:app --host 127.0.0.1 --port 8780`

Launcher behavior:
- `/home/ub/code/agent/agent/control_plane/cli/acp` with no subcommand prints usage and exits.
- `/home/ub/code/agent/agent/control_plane/cli/acp stdio` intentionally starts the MCP stdio server.

Runtime notes:
- The web UI requires `fastapi` and `uvicorn` in the active environment.
- HPC submissions delegate to `/home/ub/code/agent/agent/hpc/cli/hpc_submit_poll_fetch.sh`.
- Existing HPC job visibility remains in `/home/ub/code/agent/agent/hpc/cli/hdash`.
