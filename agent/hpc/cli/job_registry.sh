#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/storage_roots.sh"
load_storage_roots

cd "${REPO_ROOT}"

OUT_ROOT="${AGENT_HPC_LOG_ROOT}"
REGISTRY_FILE="${OUT_ROOT}/job_registry.tsv"

mkdir -p "${OUT_ROOT}"
touch "${REGISTRY_FILE}"

timestamp_now() {
  date -Iseconds
}

lock_registry() {
  exec 9>>"${REGISTRY_FILE}.lock"
  flock 9
}

has_job_id() {
  local job_id="$1"
  awk -F'\t' -v j="${job_id}" '$1 == j { found=1; exit } END { exit(found ? 0 : 1) }' "${REGISTRY_FILE}"
}

cmd="$1"
shift

case "${cmd}" in
  add)
    job_id="$1"
    submitted_at="$2"
    sbatch_file="$3"
    job_name="$4"
    remote_script="$5"
    input_method="${6:--}"
    submit_argv="${7:--}"
    lock_registry
    if has_job_id "${job_id}"; then
      exit 0
    fi
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "${job_id}" "${submitted_at}" "${sbatch_file}" "${job_name}" "${remote_script}" "SUBMITTED" "-" "-" "-" "${input_method}" "${submit_argv}" \
      >> "${REGISTRY_FILE}"
    ;;
  submit)
    job_id="$1"
    sbatch_file="$2"
    job_name="$3"
    remote_script="$4"
    submitted_at="${5:-$(date -Iseconds)}"
    input_method="${6:--}"
    submit_argv="${7:--}"
    "${SCRIPT_DIR}/job_registry.sh" add "${job_id}" "${submitted_at}" "${sbatch_file}" "${job_name}" "${remote_script}" "${input_method}" "${submit_argv}"
    ;;
  status)
    job_id="$1"
    state="$2"
    exit_code="$3"
    finished_at="${4:--}"
    lock_registry
    awk -F'\t' -v OFS='\t' -v j="${job_id}" -v s="${state}" -v e="${exit_code}" -v f="${finished_at}" '
      {
        if ($1 == j) {
          $6 = s
          $7 = e
          $8 = f
        }
        print
      }
    ' "${REGISTRY_FILE}" > "${REGISTRY_FILE}.tmp"
    mv "${REGISTRY_FILE}.tmp" "${REGISTRY_FILE}"
    ;;
  polled)
    job_id="$1"
    polled_at="${2:-$(timestamp_now)}"
    lock_registry
    awk -F'\t' -v OFS='\t' -v j="${job_id}" -v p="${polled_at}" '
      {
        if ($1 == j) {
          $9 = p
        }
        print
      }
    ' "${REGISTRY_FILE}" > "${REGISTRY_FILE}.tmp"
    mv "${REGISTRY_FILE}.tmp" "${REGISTRY_FILE}"
    ;;
  finish)
    job_id="$1"
    final_state="$2"
    final_exit="$3"
    finished_at="$4"
    "${SCRIPT_DIR}/job_registry.sh" status "${job_id}" "${final_state}" "${final_exit}" "${finished_at}"
    ;;
  show)
    sel="$1"
    case "${sel}" in
      last)
        tail -n 1 "${REGISTRY_FILE}"
        ;;
      yesterday)
        y="$(date -d 'yesterday' +%F)"
        awk -F'\t' -v y="${y}" '$2 ~ "^" y { print }' "${REGISTRY_FILE}"
        ;;
      all)
        cat "${REGISTRY_FILE}"
        ;;
    esac
    ;;
  find)
    job_id="$1"
    awk -F'\t' -v j="${job_id}" '$1 == j { print }' "${REGISTRY_FILE}"
    ;;
  ids)
    sel="$1"
    case "${sel}" in
      last)
        tail -n 1 "${REGISTRY_FILE}" | awk -F'\t' '{print $1}'
        ;;
      yesterday)
        y="$(date -d 'yesterday' +%F)"
        awk -F'\t' -v y="${y}" '$2 ~ "^" y { print $1 }' "${REGISTRY_FILE}"
        ;;
      all)
        awk -F'\t' '{print $1}' "${REGISTRY_FILE}"
        ;;
    esac
    ;;
  jobstats)
    sel="$1"
    while IFS= read -r job_id; do
      echo "=== job ${job_id} ==="
      "${SCRIPT_DIR}/hpc_ssh.sh" "bash -lc 'jobstats -j ${job_id} -l'"
    done < <("${SCRIPT_DIR}/job_registry.sh" ids "${sel}")
    ;;
  path)
    echo "${REGISTRY_FILE}"
    ;;
  archive)
    days="${1:-14}"
    archived_count="$(
      ARCHIVE_DAYS="${days}" OUT_ROOT="${OUT_ROOT}" "${PYTHON_BIN}" -c '
from tools.job_registry import JobRegistry
import os
from pathlib import Path
days = int(os.environ["ARCHIVE_DAYS"])
print(JobRegistry(Path(os.environ["OUT_ROOT"])).archive_jobs(days=days))
'
    )"
    archive_file="${OUT_ROOT}/job_registry.archive.tsv"
    printf 'archived=%s archive_file=%s\n' "${archived_count}" "${archive_file}"
    ;;
esac
