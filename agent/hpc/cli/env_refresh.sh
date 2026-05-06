#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${HPC_ENV_REFRESH_LOCAL_PYTHON:-/home/ub/mambaforge/envs/dl/bin/python}"

cd "${REPO_ROOT}"
exec "${PYTHON_BIN}" -m tools.env_refresh "$@"
