#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [[ "${1:-}" == "--login" ]]; then
  HPC_LOGIN="$2"
  export HPC_LOGIN
  shift 2
fi

LOGIN="${HPC_LOGIN:-$(python -m tools.cli load_pwd --field login)}"
CONNECT_TIMEOUT="${HPC_CONNECT_TIMEOUT:-8}"
STRICT_HOSTKEY="${HPC_STRICT_HOSTKEY:-yes}"

SSH_OPTS=(
  -o "StrictHostKeyChecking=${STRICT_HOSTKEY}"
  -o "ConnectTimeout=${CONNECT_TIMEOUT}"
)

if command -v sshpass >/dev/null 2>&1; then
  if [[ -z "${SSHPASS:-}" ]]; then
    SSHPASS="$(python -m tools.cli load_pwd --field password --show-password)"
    export SSHPASS
  fi
  exec sshpass -e ssh "${SSH_OPTS[@]}" "${LOGIN}" "$@"
fi

exec ssh "${SSH_OPTS[@]}" "${LOGIN}" "$@"
