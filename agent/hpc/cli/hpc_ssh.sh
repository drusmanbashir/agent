#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"

cd "${REPO_ROOT}"

# HPC env defaults. Callers can override any of these before invoking script.
HPC_LOGIN="${HPC_LOGIN:-}"
HPC_CONNECT_TIMEOUT="${HPC_CONNECT_TIMEOUT:-8}"
HPC_STRICT_HOSTKEY="${HPC_STRICT_HOSTKEY:-yes}"
HPC_SSH_BIN="${HPC_SSH_BIN:-ssh}"
HPC_SSHPASS_BIN="${HPC_SSHPASS_BIN:-sshpass}"
HPC_RSYNC_BIN="${HPC_RSYNC_BIN:-rsync}"

SCRIPT_FILE=""
SCRIPT_ARGS=()
RSYNC_MODE=0

while [[ $# -gt 0 ]]; do
  case "${1}" in
    --rsync)
      RSYNC_MODE=1
      shift
      break
      ;;
    --login)
      HPC_LOGIN="$2"
      export HPC_LOGIN
      shift 2
      ;;
    --script)
      SCRIPT_FILE="$2"
      shift 2
      if [[ "${1:-}" == "--" ]]; then
        shift
      fi
      SCRIPT_ARGS=("$@")
      break
      ;;
    --help)
      cat <<'USAGE'
Usage:
  cli/hpc_ssh.sh [--login user@host] 'remote command'
  cli/hpc_ssh.sh [--login user@host] --script local_script.sh -- [args...]
  cli/hpc_ssh.sh --rsync [rsync args...]
USAGE
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

LOGIN="${HPC_LOGIN:-$("${PYTHON_BIN}" -m tools.cli load_pwd --field login)}"

SSH_OPTS=(
  -o "StrictHostKeyChecking=${HPC_STRICT_HOSTKEY}"
  -o "ConnectTimeout=${HPC_CONNECT_TIMEOUT}"
)

if [[ -n "${SCRIPT_FILE}" ]]; then
  if [[ ! -r "${SCRIPT_FILE}" ]]; then
    echo "Script file not readable: ${SCRIPT_FILE}" >&2
    exit 2
  fi
  INNER_CMD="bash -s"
  if [[ ${#SCRIPT_ARGS[@]} -gt 0 ]]; then
    INNER_CMD+=" --"
    for arg in "${SCRIPT_ARGS[@]}"; do
      printf -v quoted "%q" "${arg}"
      INNER_CMD+=" ${quoted}"
    done
  fi
  printf -v quoted_inner "%q" "${INNER_CMD}"
  REMOTE_CMD="bash -lc ${quoted_inner}"
fi

if command -v "${HPC_SSHPASS_BIN}" >/dev/null 2>&1; then
  if [[ -z "${SSHPASS:-}" ]]; then
    SSHPASS="$("${PYTHON_BIN}" -m tools.cli load_pwd --field password --show-password)"
    export SSHPASS
  fi
  if [[ "${RSYNC_MODE}" == "1" ]]; then
    RSH="${HPC_SSHPASS_BIN} -e ${HPC_SSH_BIN} -o StrictHostKeyChecking=${HPC_STRICT_HOSTKEY} -o ConnectTimeout=${HPC_CONNECT_TIMEOUT}"
    exec "${HPC_RSYNC_BIN}" -e "${RSH}" "$@"
  fi
  if [[ -n "${SCRIPT_FILE}" ]]; then
    exec "${HPC_SSHPASS_BIN}" -e "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "${REMOTE_CMD}" < "${SCRIPT_FILE}"
  fi
  exec "${HPC_SSHPASS_BIN}" -e "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "$@"
fi

if [[ "${RSYNC_MODE}" == "1" ]]; then
  RSH="${HPC_SSH_BIN} -o StrictHostKeyChecking=${HPC_STRICT_HOSTKEY} -o ConnectTimeout=${HPC_CONNECT_TIMEOUT}"
  exec "${HPC_RSYNC_BIN}" -e "${RSH}" "$@"
fi

if [[ -n "${SCRIPT_FILE}" ]]; then
  exec "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "${REMOTE_CMD}" < "${SCRIPT_FILE}"
fi

exec "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "$@"
