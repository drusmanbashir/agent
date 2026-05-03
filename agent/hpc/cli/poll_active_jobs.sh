#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"

cd "${REPO_ROOT}"

u="${1:-$("${PYTHON_BIN}" -m tools.cli load_pwd --field username)}"

"${SCRIPT_DIR}/hpc_ssh.sh" "bash -lc 'squeue -u ${u} -o \"%.18i %.9P %.24j %.8u %.2t %.10M %.19S %.19e %R\"'"
