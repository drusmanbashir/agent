#!/usr/bin/env bash
set -euo pipefail

STORAGE_ROOTS_JSON="${AGENT_STORAGE_ROOTS_JSON:-/s/agent_rw/conf/agent_repo/storage_roots.json}"

storage_roots_print() {
  local json_file="${1:-${STORAGE_ROOTS_JSON}}"
  local python_bin="${PYTHON_BIN:-python3}"
  "${python_bin}" - "${json_file}" <<'PY'
import json
import shlex
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"export AGENT_STORAGE_ROOT={shlex.quote(data['storage_root'].rstrip('/'))}")
print(f"export AGENT_LOG_ROOT={shlex.quote(data['logs_root'].rstrip('/'))}")
print(f"export AGENT_TMP_ROOT={shlex.quote(data['tmp_root'].rstrip('/'))}")
print(f"export AGENT_HPC_LOG_ROOT={shlex.quote(data['hpc_logs'].rstrip('/'))}")
print(f"export AGENT_SINCLAIR_LOG_ROOT={shlex.quote(data['sinclair_logs'].rstrip('/'))}")
print(f"export AGENT_LOCAL_ACP_LOG_ROOT={shlex.quote(data['local_acp_logs'].rstrip('/'))}")
print(f"export AGENT_LOCAL_PREPROC_LOG_ROOT={shlex.quote(data['local_preproc_logs'].rstrip('/'))}")
PY
}

load_storage_roots() {
  eval "$(storage_roots_print "$@")"
  mkdir -p "${AGENT_LOG_ROOT}" "${AGENT_TMP_ROOT}" "${AGENT_HPC_LOG_ROOT}" "${AGENT_SINCLAIR_LOG_ROOT}" "${AGENT_LOCAL_ACP_LOG_ROOT}" "${AGENT_LOCAL_PREPROC_LOG_ROOT}"
}
