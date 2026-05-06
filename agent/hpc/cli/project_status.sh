#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HPC_SSH_SH="${SCRIPT_DIR}/hpc_ssh.sh"
REMOTE_PYTHON="${REMOTE_PYTHON:-/data/home/mpx588/.conda/envs/dl/bin/python}"
FRAN_REMOTE_ROOT="${FRAN_REMOTE_ROOT:-/data/EECS-LITQ/fran_storage}"
FRAN_REMOTE_CONF="${FRAN_REMOTE_CONF:-${FRAN_REMOTE_ROOT}/conf}"
FRAN_REMOTE_CODE="${FRAN_REMOTE_CODE:-${FRAN_REMOTE_ROOT}/code}"
PROJECT_STATUS_PY="${PROJECT_STATUS_PY:-${FRAN_REMOTE_CODE}/fran/fran/run/project/project_status.py}"

usage() {
  cat <<'USAGE'
Usage:
  /home/ub/code/agent/agent/hpc/cli/project_status.sh [project_name ...]

Thin wrapper over remote FRAN CLI project_status.py through hpc_ssh.sh.
All positional arguments are forwarded as project names.

Environment overrides:
  REMOTE_PYTHON
  FRAN_REMOTE_ROOT
  FRAN_REMOTE_CONF
  FRAN_REMOTE_CODE
  PROJECT_STATUS_PY
USAGE
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

PROJECT_ARGS=""
for arg in "$@"; do
  printf -v quoted_arg "%q" "${arg}"
  PROJECT_ARGS+=" ${quoted_arg}"
done

REMOTE_CMD="export FRAN_CONF=$(printf '%q' "${FRAN_REMOTE_CONF}"); export PYTHONPATH=$(printf '%q' "${FRAN_REMOTE_CODE}/localiser:${FRAN_REMOTE_CODE}/fran:${FRAN_REMOTE_CODE}/utilz:${FRAN_REMOTE_CODE}/label_analysis")\${PYTHONPATH:+:\${PYTHONPATH}}; exec $(printf '%q' "${REMOTE_PYTHON}") $(printf '%q' "${PROJECT_STATUS_PY}")${PROJECT_ARGS}"
printf -v REMOTE_SHELL 'bash -lc %q' "${REMOTE_CMD}"
exec "${HPC_SSH_SH}" "${REMOTE_SHELL}"
