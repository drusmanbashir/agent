#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

CONNECT_TIMEOUT="${HPC_CONNECT_TIMEOUT:-8}"
STRICT_HOSTKEY="${HPC_STRICT_HOSTKEY:-yes}"
RSH="ssh -o StrictHostKeyChecking=${STRICT_HOSTKEY} -o ConnectTimeout=${CONNECT_TIMEOUT}"

if command -v sshpass >/dev/null 2>&1; then
  if [[ -z "${SSHPASS:-}" ]]; then
    SSHPASS="$(python -m tools.cli load_pwd --field password --show-password)"
    export SSHPASS
  fi
  RSH="sshpass -e ${RSH}"
fi

exec rsync -e "${RSH}" "$@"
