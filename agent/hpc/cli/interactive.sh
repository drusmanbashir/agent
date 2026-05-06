#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"

cd "${REPO_ROOT}"

HPC_LOGIN="${HPC_LOGIN:-}"
HPC_CONNECT_TIMEOUT="${HPC_CONNECT_TIMEOUT:-8}"
HPC_STRICT_HOSTKEY="${HPC_STRICT_HOSTKEY:-yes}"
HPC_SSH_BIN="${HPC_SSH_BIN:-ssh}"
HPC_SSHPASS_BIN="${HPC_SSHPASS_BIN:-sshpass}"

DEFAULT_ARGS=(--ntasks=1 --cpus-per-task=16 -t 1:0:0 --mem-per-cpu=8G)

usage() {
  cat <<'EOF'
Usage:
  cli/interactive.sh [salloc args...]

Description:
  SSH into the configured HPC login with a TTY and start an interactive
  Slurm allocation via `salloc`.

Examples:
  cli/interactive.sh
  cli/interactive.sh --ntasks=1 --cpus-per-task=8 -t 0:30:0 --mem-per-cpu=6G
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
  usage
  exit 0
fi

LOGIN="${HPC_LOGIN:-$("${PYTHON_BIN}" -m tools.cli load_pwd --field login)}"
SALLOC_ARGS=("$@")
if [[ ${#SALLOC_ARGS[@]} -eq 0 ]]; then
  SALLOC_ARGS=("${DEFAULT_ARGS[@]}")
fi

printf -v remote_cmd '%q ' salloc "${SALLOC_ARGS[@]}"
remote_cmd="${remote_cmd% }"

SSH_OPTS=(
  -t
  -o "StrictHostKeyChecking=${HPC_STRICT_HOSTKEY}"
  -o "ConnectTimeout=${HPC_CONNECT_TIMEOUT}"
)

if command -v "${HPC_SSHPASS_BIN}" >/dev/null 2>&1; then
  if [[ -z "${SSHPASS:-}" ]]; then
    SSHPASS="$("${PYTHON_BIN}" -m tools.cli load_pwd --field password --show-password)"
    export SSHPASS
  fi
  exec "${HPC_SSHPASS_BIN}" -e "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "bash -lc ${remote_cmd}"
fi

exec "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "bash -lc ${remote_cmd}"
