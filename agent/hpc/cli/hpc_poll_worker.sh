#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${HPC_PYTHON_BIN:-/home/ub/mambaforge/envs/dl/bin/python}"
SSH_SCRIPT="${HPC_SSH_SCRIPT:-${SCRIPT_DIR}/hpc_ssh.sh}"
RSYNC_SCRIPT="${HPC_RSYNC_SCRIPT:-${SCRIPT_DIR}/hpc_rsync.sh}"
REGISTRY_SCRIPT="${HPC_JOB_REGISTRY_SCRIPT:-${SCRIPT_DIR}/job_registry.sh}"

cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
Usage:
  cli/hpc_poll_worker.sh spawn --job-id <job_id> --job-dir <job_dir>
  cli/hpc_poll_worker.sh run --job-id <job_id> --job-dir <job_dir>

Detached per-job Slurm poll worker used by hpc_submit_poll_fetch.sh.
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

meta_field() {
  local file="$1"
  local key="$2"
  awk -F'=' -v k="${key}" '$1 == k { print substr($0, index($0, "=") + 1); exit }' "${file}"
}

sbatch_directive_value() {
  local file="$1"
  local short_key="$2"
  local long_key="$3"
  awk -v s="${short_key}" -v l="${long_key}" '
    $1 == "#SBATCH" {
      for (i = 2; i <= NF; i++) {
        if ($i == s || $i == l) {
          if (i + 1 <= NF) {
            print $(i + 1)
            exit
          }
        }
        if (index($i, s "=") == 1 || index($i, l "=") == 1) {
          sub(/^[^=]*=/, "", $i)
          print $i
          exit
        }
      }
    }
  ' "${file}"
}

build_default_poll_schedule() {
  local minute_schedule
  local minute_step
  local second_steps=()

  minute_schedule="$("${PYTHON_BIN}" "${SCRIPT_DIR}/poll_schedule.py")"
  read -r -a minute_steps <<< "${minute_schedule}"
  for minute_step in "${minute_steps[@]}"; do
    second_steps+=("$((minute_step * 60))")
  done
  printf '%s\n' "${second_steps[*]}"
}

resolve_login() {
  if [[ -n "${HPC_LOGIN:-}" ]]; then
    printf '%s\n' "${HPC_LOGIN}"
    return 0
  fi
  "${PYTHON_BIN}" -m tools.cli load_pwd --field login
}

run_remote_bash() {
  local cmd="$1"
  local quoted=""
  printf -v quoted "%q" "${cmd}"
  "${SSH_SCRIPT}" "bash -lc ${quoted}"
}

materialize_template() {
  local tmpl="$1"
  local job_id="$2"
  local job_name="$3"
  local out="${tmpl}"
  out="${out//%j/${job_id}}"
  out="${out//%A/${job_id}}"
  out="${out//%x/${job_name}}"
  out="${out//%a/0}"
  printf '%s\n' "${out}"
}

worker_lock_is_active() {
  local lock_file="$1"
  exec 8>>"${lock_file}"
  if flock -n 8; then
    flock -u 8
    exec 8>&-
    return 1
  fi
  exec 8>&-
  return 0
}

pid_is_live() {
  local pid="$1"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

write_spawn_meta() {
  local worker_pid="$1"
  local requested_schedule="$2"
  local schedule_source="$3"
  local launched_at="$4"
  cat > "${WORKER_META_FILE}" <<EOF
job_id=${JOB_ID}
job_dir=${JOB_DIR}
worker_pid=${worker_pid}
worker_state=spawned
worker_log=${WORKER_LOG_FILE}
worker_lock=${WORKER_LOCK_FILE}
job_meta=${JOB_META_FILE}
poll_log=${POLL_LOG_FILE}
launched_at=${launched_at}
requested_poll_schedule=${requested_schedule}
poll_schedule_source=${schedule_source}
EOF
}

write_spawn_failure_meta() {
  local worker_pid="$1"
  local requested_schedule="$2"
  local schedule_source="$3"
  local launched_at="$4"
  local final_state="$5"
  local final_exit="$6"
  local finished_at="$7"
  cat > "${WORKER_META_FILE}" <<EOF
job_id=${JOB_ID}
job_dir=${JOB_DIR}
worker_pid=${worker_pid}
worker_state=failed
worker_log=${WORKER_LOG_FILE}
worker_lock=${WORKER_LOCK_FILE}
job_meta=${JOB_META_FILE}
poll_log=${POLL_LOG_FILE}
launched_at=${launched_at}
requested_poll_schedule=${requested_schedule}
poll_schedule_source=${schedule_source}
final_state=${final_state}
final_exit=${final_exit}
finished_at=${finished_at}
EOF
}

write_run_meta() {
  local worker_state="$1"
  local final_state="${2:-}"
  local final_exit="${3:-}"
  local finished_at="${4:-}"
  cat > "${WORKER_META_FILE}" <<EOF
job_id=${JOB_ID}
job_dir=${JOB_DIR}
worker_pid=$$
worker_state=${worker_state}
worker_log=${WORKER_LOG_FILE}
worker_lock=${WORKER_LOCK_FILE}
job_meta=${JOB_META_FILE}
poll_log=${POLL_LOG_FILE}
started_at=${WORKER_STARTED_AT}
poll_schedule=${POLL_SCHEDULE_STR}
poll_schedule_source=${POLL_SCHEDULE_SOURCE}
final_state=${final_state}
final_exit=${final_exit}
finished_at=${finished_at}
EOF
}

write_done_file() {
  local final_state="$1"
  local final_exit="$2"
  local finished_at="$3"
  local elapsed_raw="$4"
  local logs_fetched_at="$5"
  cat > "${WORKER_DONE_FILE}" <<EOF
job_id=${JOB_ID}
final_state=${final_state}
final_exit=${final_exit}
finished_at=${finished_at}
elapsed_raw=${elapsed_raw}
logs_fetched_at=${logs_fetched_at}
EOF
}

spawn_worker() {
  local requested_schedule=""
  local schedule_source="default"
  local worker_pid=""
  local launched_at=""
  local current_pid=""
  local worker_state=""
  local handshake_tries=0
  local spawn_failed_at=""
  local spawn_failure=""
  local spawn_sshpass="${SSHPASS:-}"
  local sshpass_bin="${HPC_SSHPASS_BIN:-sshpass}"

  exec 7>>"${WORKER_SPAWN_LOCK_FILE}"
  flock 7

  if [[ -f "${WORKER_DONE_FILE}" ]]; then
    echo "poll_worker_status=complete"
    echo "poll_worker_pid=$(cat "${WORKER_PID_FILE}" 2>/dev/null || true)"
    echo "poll_worker_log=${WORKER_LOG_FILE}"
    echo "poll_worker_meta=${WORKER_META_FILE}"
    return 0
  fi

  current_pid="$(cat "${WORKER_PID_FILE}" 2>/dev/null || true)"
  if pid_is_live "${current_pid}"; then
    echo "poll_worker_status=active"
    echo "poll_worker_pid=${current_pid}"
    echo "poll_worker_log=${WORKER_LOG_FILE}"
    echo "poll_worker_meta=${WORKER_META_FILE}"
    return 0
  fi

  if worker_lock_is_active "${WORKER_LOCK_FILE}"; then
    echo "poll_worker_status=active"
    echo "poll_worker_pid=${current_pid}"
    echo "poll_worker_log=${WORKER_LOG_FILE}"
    echo "poll_worker_meta=${WORKER_META_FILE}"
    return 0
  fi

  requested_schedule="$(meta_field "${JOB_META_FILE}" "poll_schedule" || true)"
  if [[ -n "${requested_schedule}" ]]; then
    schedule_source="explicit"
  fi

  if [[ -z "${spawn_sshpass}" ]] && command -v "${sshpass_bin}" >/dev/null 2>&1; then
    spawn_sshpass="$("${PYTHON_BIN}" -m tools.cli load_pwd --field password --show-password)"
  fi

  if [[ -n "${spawn_sshpass}" ]]; then
    SSHPASS="${spawn_sshpass}" nohup "${SCRIPT_DIR}/hpc_poll_worker.sh" run --job-id "${JOB_ID}" --job-dir "${JOB_DIR}" >> "${WORKER_LOG_FILE}" 2>&1 < /dev/null &
  else
    nohup "${SCRIPT_DIR}/hpc_poll_worker.sh" run --job-id "${JOB_ID}" --job-dir "${JOB_DIR}" >> "${WORKER_LOG_FILE}" 2>&1 < /dev/null &
  fi
  worker_pid="$!"
  launched_at="$(date -Iseconds)"
  printf '%s\n' "${worker_pid}" > "${WORKER_PID_FILE}"
  write_spawn_meta "${worker_pid}" "${requested_schedule}" "${schedule_source}" "${launched_at}"

  while (( handshake_tries < 10 )); do
    if [[ -f "${WORKER_META_FILE}" ]]; then
      worker_state="$(meta_field "${WORKER_META_FILE}" "worker_state" || true)"
    else
      worker_state=""
    fi
    case "${worker_state}" in
      running|finished|failed|stopped)
        echo "poll_worker_status=spawned"
        echo "poll_worker_pid=${worker_pid}"
        echo "poll_worker_log=${WORKER_LOG_FILE}"
        echo "poll_worker_meta=${WORKER_META_FILE}"
        return 0
        ;;
    esac
    if ! pid_is_live "${worker_pid}"; then
      spawn_failed_at="$(date -Iseconds)"
      spawn_failure="[${spawn_failed_at}] worker_spawn_failed pid=${worker_pid} before_running"
      printf '%s\n' "${spawn_failure}" >> "${WORKER_LOG_FILE}"
      printf '%s\n' "${spawn_failure}" >> "${POLL_LOG_FILE}"
      write_spawn_failure_meta "${worker_pid}" "${requested_schedule}" "${schedule_source}" "${launched_at}" "SPAWN_ERROR" "child_exited_before_running" "${spawn_failed_at}"
      echo "poll_worker_status=failed"
      echo "poll_worker_pid=${worker_pid}"
      echo "poll_worker_log=${WORKER_LOG_FILE}"
      echo "poll_worker_meta=${WORKER_META_FILE}"
      return 0
    fi
    sleep 0.2
    handshake_tries=$((handshake_tries + 1))
  done

  if [[ -f "${WORKER_META_FILE}" ]]; then
    worker_state="$(meta_field "${WORKER_META_FILE}" "worker_state" || true)"
  else
    worker_state=""
  fi
  case "${worker_state}" in
    running|finished|failed|stopped)
      ;;
    *)
      write_spawn_meta "${worker_pid}" "${requested_schedule}" "${schedule_source}" "${launched_at}"
      ;;
  esac

  echo "poll_worker_status=spawned"
  echo "poll_worker_pid=${worker_pid}"
  echo "poll_worker_log=${WORKER_LOG_FILE}"
  echo "poll_worker_meta=${WORKER_META_FILE}"
}

run_worker() {
  local requested_schedule=""
  local schedule_steps=()
  local idx=0
  local sleep_for=0
  local squeue_line=""
  local final_line=""
  local final_state="UNKNOWN"
  local final_exit="-"
  local elapsed_raw="0"
  local finished_at=""
  local logs_fetched_at=""
  local job_name=""
  local sbatch_file=""
  local log_out_template=""
  local log_err_template=""
  local remote_out=""
  local remote_err=""
  local local_out=""
  local local_err=""
  local login=""
  RUN_WORKER_COMPLETED=0
  RUN_WORKER_ERR_LINE=""
  RUN_WORKER_ERR_CMD=""
  RUN_WORKER_ERR_STATUS=0

  worker_on_err() {
    RUN_WORKER_ERR_STATUS="$1"
    RUN_WORKER_ERR_LINE="$2"
    RUN_WORKER_ERR_CMD="$3"
  }

  worker_on_exit() {
    local exit_code="$1"
    local finished_at=""
    local failure_status=0
    local failure_line="?"
    local failure_cmd="unknown"
    local message=""

    if [[ "${RUN_WORKER_COMPLETED:-0}" == "1" ]]; then
      return 0
    fi

    trap - ERR EXIT
    set +e

    finished_at="$(date -Iseconds)"
    if [[ -n "${RUN_WORKER_ERR_CMD:-}" || "${exit_code}" -ne 0 ]]; then
      failure_status="${RUN_WORKER_ERR_STATUS:-${exit_code}}"
      [[ -n "${RUN_WORKER_ERR_LINE:-}" ]] && failure_line="${RUN_WORKER_ERR_LINE}"
      [[ -n "${RUN_WORKER_ERR_CMD:-}" ]] && failure_cmd="${RUN_WORKER_ERR_CMD}"
      message="[${finished_at}] worker_error exit=${failure_status} line=${failure_line} cmd=${failure_cmd}"
      printf '%s\n' "${message}" >> "${WORKER_LOG_FILE}"
      printf '%s\n' "${message}" >> "${POLL_LOG_FILE}"
      write_run_meta "failed" "WORKER_ERROR" "${failure_status}" "${finished_at}"
      return 0
    fi

    message="[${finished_at}] worker_exit_before_completion exit=0"
    printf '%s\n' "${message}" >> "${WORKER_LOG_FILE}"
    printf '%s\n' "${message}" >> "${POLL_LOG_FILE}"
    write_run_meta "stopped" "-" "-" "${finished_at}"
  }

  exec 9>>"${WORKER_LOCK_FILE}"
  if ! flock -n 9; then
    echo "poll_worker_status=active"
    exit 0
  fi

  [[ -f "${JOB_META_FILE}" ]] || die "missing job metadata: ${JOB_META_FILE}"
  trap 'worker_on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR
  trap 'worker_on_exit "$?"' EXIT

  job_name="$(meta_field "${JOB_META_FILE}" "job_name" || true)"
  sbatch_file="$(meta_field "${JOB_META_FILE}" "sbatch_file" || true)"
  requested_schedule="$(meta_field "${JOB_META_FILE}" "poll_schedule" || true)"
  log_out_template="$(meta_field "${JOB_META_FILE}" "log_out_template" || true)"
  log_err_template="$(meta_field "${JOB_META_FILE}" "log_err_template" || true)"
  [[ -n "${job_name}" ]] || job_name="job_${JOB_ID}"

  if [[ -n "${requested_schedule}" ]]; then
    POLL_SCHEDULE_STR="${requested_schedule}"
    POLL_SCHEDULE_SOURCE="explicit"
  else
    POLL_SCHEDULE_STR="$(build_default_poll_schedule)"
    POLL_SCHEDULE_SOURCE="default"
  fi
  read -r -a schedule_steps <<< "${POLL_SCHEDULE_STR}"

  WORKER_STARTED_AT="$(date -Iseconds)"
  rm -f "${WORKER_DONE_FILE}"
  printf '%s\n' "$$" > "${WORKER_PID_FILE}"
  write_run_meta "running"

  : > "${POLL_LOG_FILE}"
  echo "poll_worker_status=running job_id=${JOB_ID} schedule=${POLL_SCHEDULE_STR}"

  while true; do
    squeue_line="$(run_remote_bash "squeue -h -j ${JOB_ID} -o '%i|%T|%M|%R' 2>/dev/null" | tail -n 1 || true)"
    if [[ -z "${squeue_line}" ]]; then
      break
    fi

    echo "${squeue_line}" >> "${POLL_LOG_FILE}"
    "${REGISTRY_SCRIPT}" status "${JOB_ID}" "$(awk -F'|' '{print $2}' <<< "${squeue_line}")" "-" "-"
    "${REGISTRY_SCRIPT}" polled "${JOB_ID}"

    if [[ "${idx}" -lt "${#schedule_steps[@]}" ]]; then
      sleep_for="${schedule_steps[${idx}]}"
    else
      sleep_for="${schedule_steps[-1]}"
    fi
    sleep "${sleep_for}"
    idx=$((idx + 1))
  done

  final_line="$(run_remote_bash "sacct -n -P -j ${JOB_ID} --format=JobIDRaw,State,ExitCode,ElapsedRaw 2>/dev/null | awk -F'|' -v id='${JOB_ID}' '\$1==id {print \$0; exit}'" | tail -n 1 || true)"
  if [[ -n "${final_line}" ]]; then
    echo "${final_line}" >> "${POLL_LOG_FILE}"
    final_state="$(awk -F'|' '{print $2}' <<< "${final_line}")"
    final_exit="$(awk -F'|' '{print $3}' <<< "${final_line}")"
    elapsed_raw="$(awk -F'|' '{print $4}' <<< "${final_line}")"
  fi
  [[ -n "${final_state}" ]] || final_state="UNKNOWN"
  [[ -n "${final_exit}" ]] || final_exit="-"
  [[ -n "${elapsed_raw}" ]] || elapsed_raw="0"
  "${REGISTRY_SCRIPT}" polled "${JOB_ID}"

  finished_at="$(date -Iseconds)"
  "${REGISTRY_SCRIPT}" finish "${JOB_ID}" "${final_state}" "${final_exit}" "${finished_at}"

  if [[ -z "${log_out_template}" && -n "${sbatch_file}" && -r "${sbatch_file}" ]]; then
    log_out_template="$(sbatch_directive_value "${sbatch_file}" "-o" "--output" || true)"
  fi
  if [[ -z "${log_err_template}" && -n "${sbatch_file}" && -r "${sbatch_file}" ]]; then
    log_err_template="$(sbatch_directive_value "${sbatch_file}" "-e" "--error" || true)"
  fi
  [[ -n "${log_out_template}" ]] || log_out_template="slurm-%j.out"
  [[ -n "${log_err_template}" ]] || log_err_template="${log_out_template}"

  remote_out="$(materialize_template "${log_out_template}" "${JOB_ID}" "${job_name}")"
  remote_err="$(materialize_template "${log_err_template}" "${JOB_ID}" "${job_name}")"

  login="$(resolve_login)"
  echo "Fetching ${remote_out}"
  "${RSYNC_SCRIPT}" -az "${login}:${remote_out}" "${JOB_DIR}/"

  if [[ "${remote_err}" != "${remote_out}" ]]; then
    echo "Fetching ${remote_err}"
    "${RSYNC_SCRIPT}" -az "${login}:${remote_err}" "${JOB_DIR}/"
  fi

  local_out="${JOB_DIR}/$(basename "${remote_out}")"
  if [[ "${remote_err}" == "${remote_out}" ]]; then
    local_err="${local_out}"
  else
    local_err="${JOB_DIR}/$(basename "${remote_err}")"
  fi

  if [[ "${elapsed_raw}" =~ ^[0-9]+$ ]] && (( elapsed_raw > 300 )); then
    cp -f "${local_out}" "${JOB_DIR}/std.out"
    cp -f "${local_err}" "${JOB_DIR}/std.err"
    echo "Job runtime ${elapsed_raw}s > 300s; prepared ${JOB_DIR}/std.out and ${JOB_DIR}/std.err"
  fi

  logs_fetched_at="$(date -Iseconds)"
  write_done_file "${final_state}" "${final_exit}" "${finished_at}" "${elapsed_raw}" "${logs_fetched_at}"
  write_run_meta "finished" "${final_state}" "${final_exit}" "${finished_at}"
  RUN_WORKER_COMPLETED=1
  trap - ERR EXIT

  echo "poll_worker_status=finished job_id=${JOB_ID} state=${final_state} exit=${final_exit}"
  echo "poll_worker_logs=${JOB_DIR}"
}

COMMAND="${1:-}"
[[ -n "${COMMAND}" ]] || {
  usage >&2
  exit 2
}
shift

JOB_ID=""
JOB_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-id)
      JOB_ID="$2"
      shift 2
      ;;
    --job-dir)
      JOB_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "${JOB_ID}" ]] || die "--job-id is required"
[[ -n "${JOB_DIR}" ]] || die "--job-dir is required"

mkdir -p "${JOB_DIR}"

JOB_META_FILE="${JOB_DIR}/job.meta"
WORKER_PID_FILE="${JOB_DIR}/worker.pid"
WORKER_META_FILE="${JOB_DIR}/worker.meta"
WORKER_DONE_FILE="${JOB_DIR}/worker.done"
WORKER_LOG_FILE="${JOB_DIR}/worker.log"
WORKER_LOCK_FILE="${JOB_DIR}/worker.lock"
WORKER_SPAWN_LOCK_FILE="${JOB_DIR}/worker.spawn.lock"
POLL_LOG_FILE="${JOB_DIR}/poll.log"
POLL_SCHEDULE_STR=""
POLL_SCHEDULE_SOURCE=""
WORKER_STARTED_AT=""

case "${COMMAND}" in
  spawn)
    spawn_worker
    ;;
  run)
    run_worker
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    usage >&2
    exit 2
    ;;
esac
