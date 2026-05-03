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
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --login" >&2
        exit 2
      fi
      HPC_LOGIN="$2"
      export HPC_LOGIN
      shift 2
      ;;
    --script)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --script" >&2
        exit 2
      fi
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
  cli/hpc_ssh_nopass.sh [--login user@host] 'remote command'
  cli/hpc_ssh_nopass.sh [--login user@host] --script local_script.sh -- [args...]
  cli/hpc_ssh_nopass.sh --rsync [rsync args...]
EOF
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

LOGIN="${HPC_LOGIN:-}"
if [[ -z "${LOGIN}" ]]; then
  if ! LOGIN="$("${PYTHON_BIN}" -m tools.cli load_pwd --field login)"; then
    echo "Failed to resolve login via: ${PYTHON_BIN} -m tools.cli load_pwd --field login" >&2
    exit 2
  fi
fi
if [[ -z "${LOGIN}" ]]; then
  echo "Resolved login is empty. Set --login or configure hpc.yaml login." >&2
  exit 2
fi

SSH_OPTS=(
  -o "BatchMode=yes"
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

print_key_auth_help() {
  cat >&2 <<EOF
Key auth failed for ${LOGIN}.
Set up SSH keys, then retry:
  ssh-keygen -t ed25519
  ssh-copy-id ${LOGIN}
EOF
}

status=0
if [[ "${RSYNC_MODE}" == "1" ]]; then
  RSH="${HPC_SSH_BIN} -o BatchMode=yes -o StrictHostKeyChecking=${HPC_STRICT_HOSTKEY} -o ConnectTimeout=${HPC_CONNECT_TIMEOUT}"
  set +e
  "${HPC_RSYNC_BIN}" -e "${RSH}" "$@"
  status=$?
  set -e
else
  set +e
  if [[ -n "${SCRIPT_FILE}" ]]; then
    "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "${REMOTE_CMD}" < "${SCRIPT_FILE}"
  else
    "${HPC_SSH_BIN}" "${SSH_OPTS[@]}" "${LOGIN}" "$@"
  fi
  status=$?
  set -e
fi

if [[ "${status}" -eq 255 ]]; then
  print_key_auth_help
fi

exit "${status}"
