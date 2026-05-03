#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CALLER_CWD="$(pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"

usage() {
  cat <<'EOF'
Usage: cli/hpc_submit_poll_fetch.sh [--poll-schedule "60 120 900"] [--sbatch-arg <arg>]... <local_sbatch_script> [script args...]

Submit a Slurm script, poll until completion, and fetch that job's stdout/stderr
into the local job folder. If the job runtime exceeds 5 minutes, also copy those
logs to local `std.out` and `std.err` files and open them in Neovim when run from
an interactive terminal with `nvim` available.
EOF
}

POLL_SCHEDULE_RAW="${HPC_SBATCH_POLL_SCHEDULE:-120 600}"
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
  tmp_submit_file="$(mktemp "${TMPDIR:-/tmp}/hpc-submit.XXXXXX.sh")"
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

OUT_ROOT="${HPC_LOGS_LOCAL_ROOT:-${HPC_JOBS_LOCAL_ROOT:-/s/agent_rw/hpc_logs}}"
REMOTE_DIR="${HPC_SBATCH_REMOTE_DIR:-.hpc/sbatch}"
LOGIN="${HPC_LOGIN:-$("${PYTHON_BIN}" -m tools.cli load_pwd --field login)}"
POLL_SCHEDULE_STR="${POLL_SCHEDULE_RAW}"

job_name="$(awk '/^#SBATCH[[:space:]]+-J[[:space:]]+/ {print $3; exit}' "${submit_file}")"
log_out_template="$(awk '/^#SBATCH[[:space:]]+-o[[:space:]]+/ {print $3; exit}' "${submit_file}")"
log_err_template="$(awk '/^#SBATCH[[:space:]]+-e[[:space:]]+/ {print $3; exit}' "${submit_file}")"

base_name="$(basename "${SBATCH_FILE}")"
remote_dir_q="$(printf "%q" "${REMOTE_DIR}")"
remote_template_q="$(printf "%q" "${REMOTE_DIR}/${base_name%.sh}.XXXXXX.sh")"
remote_script="$("${SCRIPT_DIR}/hpc_ssh.sh" "mkdir -p ${remote_dir_q} && mktemp ${remote_template_q}" | tail -n 1)"
"${SCRIPT_DIR}/hpc_rsync.sh" -az "${submit_file}" "${LOGIN}:${remote_script}" >/dev/null
if [[ -n "${tmp_submit_file}" ]]; then
  rm -f "${tmp_submit_file}"
fi

remote_script_q="$(printf "%q" "${remote_script}")"
poll_schedule_q="${POLL_SCHEDULE_STR}"
script_args_q=()
for arg in "$@"; do
  script_args_q+=("$(printf "%q" "${arg}")")
done
sbatch_extra_args_q=()
for arg in "${SBATCH_EXTRA_ARGS[@]}"; do
  sbatch_extra_args_q+=("$(printf "%q" "${arg}")")
done

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

sbatch_ntasks_q=""
inferred_ntasks="$(infer_sbatch_ntasks_from_script_args "$@" || true)"
if [[ -n "${inferred_ntasks:-}" ]]; then
  sbatch_ntasks_q="$(printf "%q" "--ntasks=${inferred_ntasks}")"
fi

read -r -d '' submit_inner <<EOF || true
set -euo pipefail
chmod +x ${remote_script_q}
sbatch --parsable ${sbatch_ntasks_q} ${sbatch_extra_args_q[*]} ${remote_script_q} ${script_args_q[*]} | awk -F';' '{print \$1}'
EOF

job_id="$("${SCRIPT_DIR}/hpc_ssh.sh" "bash -lc $(printf "%q" "${submit_inner}")" | tail -n 1)"
job_dir="${OUT_ROOT}/${job_id}"
mkdir -p "${job_dir}"
submitted_at="$(date -Iseconds)"

"${SCRIPT_DIR}/job_registry.sh" add "${job_id}" "${submitted_at}" "${SBATCH_FILE}" "${job_name}" "${remote_script}"

{
  echo "job_id=${job_id}"
  echo "job_name=${job_name}"
  echo "submitted_at=${submitted_at}"
  echo "sbatch_file=${SBATCH_FILE}"
  echo "remote_script=${remote_script}"
} > "${job_dir}/job.meta"

echo "Submitted batch job ${job_id}"
echo "Polling via schedule: ${POLL_SCHEDULE_STR}"

read -r -d '' poll_inner <<EOF || true
set -euo pipefail
poll_schedule="${poll_schedule_q}"
read -r -a poll_steps <<< "\${poll_schedule}"
idx=0
while squeue -h -j ${job_id} | grep -q .; do
  squeue -h -j ${job_id} -o '%i|%T|%M|%R'
  if [[ "\${idx}" -lt "\${#poll_steps[@]}" ]]; then
    sleep "\${poll_steps[\${idx}]}"
  else
    sleep "\${poll_steps[-1]}"
  fi
  idx=\$((idx+1))
done
sacct -n -P -j ${job_id} --format=JobIDRaw,State,ExitCode,ElapsedRaw | awk -F'|' -v id='${job_id}' '\$1==id {print \$0; exit}'
EOF

"${SCRIPT_DIR}/hpc_ssh.sh" "bash -lc $(printf "%q" "${poll_inner}")" | tee "${job_dir}/poll.log"
final_line="$(tail -n 1 "${job_dir}/poll.log")"
final_state="$(echo "${final_line}" | awk -F'|' '{print $2}')"
final_exit="$(echo "${final_line}" | awk -F'|' '{print $3}')"
elapsed_raw="$(echo "${final_line}" | awk -F'|' '{print $4}')"
finished_at="$(date -Iseconds)"

"${SCRIPT_DIR}/job_registry.sh" finish "${job_id}" "${final_state}" "${final_exit}" "${finished_at}"

remote_out="${log_out_template//%x/${job_name}}"
remote_out="${remote_out//%j/${job_id}}"
remote_err="${log_err_template//%x/${job_name}}"
remote_err="${remote_err//%j/${job_id}}"

echo "Fetching ${remote_out}"
echo "Fetching ${remote_err}"
"${SCRIPT_DIR}/hpc_rsync.sh" -az "${LOGIN}:${remote_out}" "${job_dir}/"
"${SCRIPT_DIR}/hpc_rsync.sh" -az "${LOGIN}:${remote_err}" "${job_dir}/"

local_out="${job_dir}/$(basename "${remote_out}")"
local_err="${job_dir}/$(basename "${remote_err}")"

if [[ "${elapsed_raw}" =~ ^[0-9]+$ ]] && (( elapsed_raw > 300 )); then
  cp -f "${local_out}" "${job_dir}/std.out"
  cp -f "${local_err}" "${job_dir}/std.err"
  echo "Job runtime ${elapsed_raw}s > 300s; prepared ${job_dir}/std.out and ${job_dir}/std.err"
  if command -v nvim >/dev/null 2>&1 && [[ -t 0 && -t 1 ]]; then
    echo "Opening long-run logs in nvim"
    nvim -p "${job_dir}/std.out" "${job_dir}/std.err"
  else
    echo "Skipping nvim auto-open: interactive terminal or nvim not available"
  fi
fi

echo "Saved job files in ${job_dir}"
