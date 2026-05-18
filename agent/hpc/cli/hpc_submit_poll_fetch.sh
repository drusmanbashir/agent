#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CALLER_CWD="$(pwd)"
PYTHON_BIN="${HPC_PYTHON_BIN:-/home/ub/mambaforge/envs/dl/bin/python}"
SSH_SCRIPT="${HPC_SSH_SCRIPT:-${SCRIPT_DIR}/hpc_ssh.sh}"
RSYNC_SCRIPT="${HPC_RSYNC_SCRIPT:-${SCRIPT_DIR}/hpc_rsync.sh}"
REGISTRY_SCRIPT="${HPC_JOB_REGISTRY_SCRIPT:-${SCRIPT_DIR}/job_registry.sh}"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/storage_roots.sh"
load_storage_roots

usage() {
  cat <<'EOF'
Usage: cli/hpc_submit_poll_fetch.sh [--poll-schedule "60 120 900"] [--sbatch-arg <arg>]... <local_sbatch_script> [script args...]

Submit a Slurm script, write local job metadata, start a detached per-job poll
worker, and return immediately. The worker handles Slurm polling, registry
updates, and log fetch into the local job folder after terminal completion.
EOF
}

shell_join_quoted() {
  local out=()
  local arg=""
  for arg in "$@"; do
    out+=("$(printf "%q" "${arg}")")
  done
  printf '%s\n' "${out[*]}"
}

ORIGINAL_ARGV=("$@")
POLL_SCHEDULE_RAW="${HPC_SBATCH_POLL_SCHEDULE:-}"
SBATCH_EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --poll-schedule)
      POLL_SCHEDULE_RAW="$2"
      shift 2
      ;;
    --sbatch-arg)
      SBATCH_EXTRA_ARGS+=("$2")
      shift 2
      ;;
    --sbatch-arg=*)
      SBATCH_EXTRA_ARGS+=("${1#*=}")
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

SBATCH_FILE="$1"
shift

if [[ "${SBATCH_FILE}" != /* ]]; then
  SBATCH_FILE="${CALLER_CWD}/${SBATCH_FILE}"
fi

submit_file="${SBATCH_FILE}"
tmp_submit_file=""

has_mem_override=false
for arg in "${SBATCH_EXTRA_ARGS[@]}"; do
  case "${arg}" in
    --mem=*|--mem|--mem-per-cpu=*|--mem-per-cpu|--mem-per-gpu=*|--mem-per-gpu)
      has_mem_override=true
      ;;
  esac
done

if [[ "${has_mem_override}" == "true" ]]; then
  tmp_submit_file="$(mktemp "${AGENT_TMP_ROOT}/hpc-submit.XXXXXX.sh")"
  awk '
    /^#SBATCH[[:space:]]+--mem([=[:space:]].*)?$/ { next }
    /^#SBATCH[[:space:]]+--mem-per-cpu([=[:space:]].*)?$/ { next }
    /^#SBATCH[[:space:]]+--mem-per-gpu([=[:space:]].*)?$/ { next }
    { print }
  ' "${SBATCH_FILE}" > "${tmp_submit_file}"
  chmod +x "${tmp_submit_file}"
  submit_file="${tmp_submit_file}"
fi

cd "${REPO_ROOT}"

OUT_ROOT="${AGENT_HPC_LOG_ROOT}"
REMOTE_DIR="${HPC_SBATCH_REMOTE_DIR:-.hpc/sbatch}"
LOGIN="${HPC_LOGIN:-$("${PYTHON_BIN}" -m tools.cli load_pwd --field login)}"

job_name="$(awk '/^#SBATCH[[:space:]]+-J[[:space:]]+/ {print $3; exit}' "${submit_file}")"
log_out_template="$(awk '/^#SBATCH[[:space:]]+-o[[:space:]]+/ {print $3; exit}' "${submit_file}")"
log_err_template="$(awk '/^#SBATCH[[:space:]]+-e[[:space:]]+/ {print $3; exit}' "${submit_file}")"

base_name="$(basename "${SBATCH_FILE}")"
remote_dir_q="$(printf "%q" "${REMOTE_DIR}")"
remote_template_q="$(printf "%q" "${REMOTE_DIR}/${base_name%.sh}.XXXXXX.sh")"
remote_script="$("${SSH_SCRIPT}" "mkdir -p ${remote_dir_q} && mktemp ${remote_template_q}" | tail -n 1)"
"${RSYNC_SCRIPT}" -az "${submit_file}" "${LOGIN}:${remote_script}" >/dev/null
if [[ -n "${tmp_submit_file}" ]]; then
  rm -f "${tmp_submit_file}"
fi

remote_script_q="$(printf "%q" "${remote_script}")"
script_args_q=()
for arg in "$@"; do
  script_args_q+=("$(printf "%q" "${arg}")")
done
sbatch_extra_args_q=()
for arg in "${SBATCH_EXTRA_ARGS[@]}"; do
  sbatch_extra_args_q+=("$(printf "%q" "${arg}")")
done
submit_argv_raw="$(shell_join_quoted "${ORIGINAL_ARGV[@]}")"
script_args_raw="$(shell_join_quoted "$@")"

infer_sbatch_ntasks_from_script_args() {
  local prev=""
  for arg in "$@"; do
    if [[ "${prev}" == "-n" || "${prev}" == "--num-processes" ]]; then
      printf '%s\n' "${arg}"
      return 0
    fi
    case "${arg}" in
      -n=*|--num-processes=*)
        printf '%s\n' "${arg#*=}"
        return 0
        ;;
    esac
    prev="${arg}"
  done
  return 1
}

infer_sbatch_cpus_per_task_from_script_args() {
  local prev=""
  for arg in "$@"; do
    if [[ "${prev}" == "-c" || "${prev}" == "--cpus-per-task" ]]; then
      printf '%s\n' "${arg}"
      return 0
    fi
    case "${arg}" in
      -c=*|--cpus-per-task=*)
        printf '%s\n' "${arg#*=}"
        return 0
        ;;
    esac
    prev="${arg}"
  done
  return 1
}

submit_uses_num_processes_for_cpus() {
  case "$(basename "${SBATCH_FILE}")" in
    preproc.sh)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

sbatch_ntasks_q=""
if ! submit_uses_num_processes_for_cpus; then
  inferred_ntasks="$(infer_sbatch_ntasks_from_script_args "$@" || true)"
  if [[ -n "${inferred_ntasks:-}" ]]; then
    sbatch_ntasks_q="$(printf "%q" "--ntasks=${inferred_ntasks}")"
  fi
fi

sbatch_cpus_per_task_q=""
inferred_cpus_per_task="$(infer_sbatch_cpus_per_task_from_script_args "$@" || true)"
if [[ -z "${inferred_cpus_per_task:-}" ]] && submit_uses_num_processes_for_cpus; then
  inferred_cpus_per_task="$(infer_sbatch_ntasks_from_script_args "$@" || true)"
fi
if [[ -n "${inferred_cpus_per_task:-}" ]]; then
  sbatch_cpus_per_task_q="$(printf "%q" "--cpus-per-task=${inferred_cpus_per_task}")"
fi

read -r -d '' submit_inner <<EOF || true
set -euo pipefail
chmod +x ${remote_script_q}
sbatch --parsable ${sbatch_ntasks_q} ${sbatch_cpus_per_task_q} ${sbatch_extra_args_q[*]} ${remote_script_q} ${script_args_q[*]} | awk -F';' '{print \$1}'
EOF

job_id="$("${SSH_SCRIPT}" "bash -lc $(printf "%q" "${submit_inner}")" | tail -n 1)"
job_dir="${OUT_ROOT}/${job_id}"
mkdir -p "${job_dir}"
submitted_at="$(date -Iseconds)"

"${REGISTRY_SCRIPT}" add "${job_id}" "${submitted_at}" "${SBATCH_FILE}" "${job_name}" "${remote_script}" "hpc_submit_poll_fetch" "${submit_argv_raw}"

{
  echo "input_method=hpc_submit_poll_fetch"
  echo "submit_argv=${submit_argv_raw}"
  echo "script_args=${script_args_raw}"
  echo "job_id=${job_id}"
  echo "job_name=${job_name}"
  echo "submitted_at=${submitted_at}"
  echo "sbatch_file=${SBATCH_FILE}"
  echo "remote_script=${remote_script}"
  echo "poll_schedule=${POLL_SCHEDULE_RAW}"
  echo "log_out_template=${log_out_template}"
  echo "log_err_template=${log_err_template}"
} > "${job_dir}/job.meta"

echo "Submitted batch job ${job_id}"
"${SCRIPT_DIR}/hpc_poll_worker.sh" spawn --job-id "${job_id}" --job-dir "${job_dir}"
echo "job_dir=${job_dir}"
echo "manual_logs=cli/hpc_poll_logs.sh ${job_id}"
