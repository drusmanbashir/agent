#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

SCRIPT_FILE=""
SCRIPT_ARGS=()

while [[ $# -gt 0 ]]; do
  case "${1}" in
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
      cat <<'EOF'
Usage:
  scripts/hpc_ssh.sh [--login user@host] 'remote command'
  scripts/hpc_ssh.sh [--login user@host] --script local_script.sh -- [args...]
EOF
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

LOGIN="${HPC_LOGIN:-$(python -m tools.cli load_pwd --field login)}"
CONNECT_TIMEOUT="${HPC_CONNECT_TIMEOUT:-8}"
STRICT_HOSTKEY="${HPC_STRICT_HOSTKEY:-yes}"

SSH_OPTS=(
  -o "StrictHostKeyChecking=${STRICT_HOSTKEY}"
  -o "ConnectTimeout=${CONNECT_TIMEOUT}"
)

if [[ -n "${SCRIPT_FILE}" ]]; then
  if [[ ! -r "${SCRIPT_FILE}" ]]; then
    echo "Script file not readable: ${SCRIPT_FILE}" >&2
    exit 2
  fi
  REMOTE_CMD="bash -s"
  if [[ ${#SCRIPT_ARGS[@]} -gt 0 ]]; then
    REMOTE_CMD+=" --"
    for arg in "${SCRIPT_ARGS[@]}"; do
      printf -v quoted "%q" "${arg}"
      REMOTE_CMD+=" ${quoted}"
    done
  fi
fi

if command -v sshpass >/dev/null 2>&1; then
  if [[ -z "${SSHPASS:-}" ]]; then
    SSHPASS="$(python -m tools.cli load_pwd --field password --show-password)"
    export SSHPASS
  fi
  if [[ -n "${SCRIPT_FILE}" ]]; then
    exec sshpass -e ssh "${SSH_OPTS[@]}" "${LOGIN}" "${REMOTE_CMD}" < "${SCRIPT_FILE}"
  fi
  exec sshpass -e ssh "${SSH_OPTS[@]}" "${LOGIN}" "$@"
fi

if [[ -n "${SCRIPT_FILE}" ]]; then
  exec ssh "${SSH_OPTS[@]}" "${LOGIN}" "${REMOTE_CMD}" < "${SCRIPT_FILE}"
fi

exec ssh "${SSH_OPTS[@]}" "${LOGIN}" "$@"
