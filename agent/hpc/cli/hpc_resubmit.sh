#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
OUT_ROOT="${HPC_LOGS_LOCAL_ROOT:-${HPC_JOBS_LOCAL_ROOT:-/s/agent_rw/hpc_logs}}"
SUBMIT_SCRIPT="${HPC_RESUBMIT_SUBMIT_SCRIPT:-${SCRIPT_DIR}/hpc_submit_poll_fetch.sh}"

usage() {
  cat <<'EOF'
Usage:
  cli/hpc_resubmit.sh <job_id>
EOF
}

meta_field() {
  local file="$1"
  local key="$2"
  awk -F'=' -v k="${key}" '$1 == k { print substr($0, index($0, "=") + 1); exit }' "${file}"
}

job_id="${1:-}"
if [[ -z "${job_id}" || "${job_id}" == "-h" || "${job_id}" == "--help" ]]; then
  usage
  if [[ -z "${job_id}" ]]; then
    exit 2
  fi
  exit 0
fi
if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

job_meta="${OUT_ROOT}/${job_id}/job.meta"
[[ -f "${job_meta}" ]] || {
  echo "missing job metadata: ${job_meta}" >&2
  exit 1
}

input_method="$(meta_field "${job_meta}" "input_method" || true)"
[[ "${input_method}" == "hpc_submit_poll_fetch" ]] || {
  echo "unsupported input_method in ${job_meta}: ${input_method:-missing}" >&2
  exit 1
}

submit_argv="$(meta_field "${job_meta}" "submit_argv" || true)"
[[ -n "${submit_argv}" ]] || {
  echo "submit_argv missing in ${job_meta}" >&2
  exit 1
}

eval "set -- ${submit_argv}"
cd "${REPO_ROOT}"
exec "${SUBMIT_SCRIPT}" "$@"
