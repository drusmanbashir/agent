#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/storage_roots.sh"
load_storage_roots

cd "${REPO_ROOT}"

OUT_ROOT="${AGENT_HPC_LOG_ROOT}"

usage() {
  cat <<EOF
Usage:
  cli/hpc_poll_logs.sh [last|<job_id>]

Description:
  Canonical poll command for stdout/stderr retrieval.
  - Defaults to the last job ID.
  - If job_registry.tsv has no rows, resolves last job from newest dir under ${AGENT_HPC_LOG_ROOT}.
  - Ensures fetched job copies and canonical std.out/std.err under ${AGENT_HPC_LOG_ROOT}/<job_id>/.
  - Echoes stdout first, then always echoes stderr.
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

mkdir -p "${OUT_ROOT}"

pick_newest_job_dir() {
  local id=""
  id="$(find "${OUT_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' 2>/dev/null \
    | awk '$2 ~ /^[0-9]+$/ {print}' | sort -nr | awk 'NR==1 {print $2}')"
  if [[ -n "${id}" ]]; then
    printf '%s\n' "${id}"
    return 0
  fi
  find "${OUT_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' 2>/dev/null \
    | sort -nr | awk 'NR==1 {print $2}'
}

resolve_job_id() {
  local requested="$1"
  if [[ "${requested}" != "last" ]]; then
    printf '%s\n' "${requested}"
    return 0
  fi

  local id=""
  id="$("${SCRIPT_DIR}/job_registry.sh" ids last 2>/dev/null || true)"
  id="$(echo "${id}" | tr -d '[:space:]')"
  if [[ -n "${id}" ]]; then
    printf '%s\n' "${id}"
    return 0
  fi

  id="$(pick_newest_job_dir || true)"
  id="$(echo "${id}" | tr -d '[:space:]')"
  if [[ -n "${id}" ]]; then
    printf '%s\n' "${id}"
    return 0
  fi

  return 1
}

row_field() {
  local row="$1"
  local idx="$2"
  awk -F'\t' -v i="${idx}" 'NF >= i { print $i }' <<< "${row}"
}

meta_field() {
  local file="$1"
  local key="$2"
  awk -F'=' -v k="${key}" '$1 == k { print substr($0, index($0, "=") + 1); exit }' "${file}"
}

find_log_file() {
  local dir="$1"
  local ext="$2"
  local exact="${dir}/std.${ext}"
  if [[ -f "${exact}" ]]; then
    printf '%s\n' "${exact}"
    return 0
  fi
  find "${dir}" -maxdepth 1 -type f -name "*.${ext}" -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk 'NR==1 { sub(/^[^ ]+ /, ""); print }'
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
  "${SCRIPT_DIR}/hpc_ssh.sh" "bash -lc ${quoted}"
}

resolve_remote_paths_from_slurm() {
  local job_id="$1"
  local out=""
  local err=""
  local scontrol_line=""
  local sacct_line=""

  scontrol_line="$(run_remote_bash "scontrol show job -o ${job_id} 2>/dev/null" | tail -n 1 || true)"
  if [[ -n "${scontrol_line}" ]]; then
    out="$(awk 'match($0, /StdOut=[^ ]+/) { v = substr($0, RSTART + 7, RLENGTH - 7); print v; exit }' <<< "${scontrol_line}")"
    err="$(awk 'match($0, /StdErr=[^ ]+/) { v = substr($0, RSTART + 7, RLENGTH - 7); print v; exit }' <<< "${scontrol_line}")"
  fi

  if [[ -z "${out}" || -z "${err}" ]]; then
    sacct_line="$(run_remote_bash "sacct -n -P -j ${job_id} --format=JobIDRaw,StdOut,StdErr 2>/dev/null" \
      | awk -F'|' -v id="${job_id}" '$1 == id {print $0; exit}' || true)"
    if [[ -n "${sacct_line}" ]]; then
      [[ -z "${out}" ]] && out="$(awk -F'|' '{print $2}' <<< "${sacct_line}")"
      [[ -z "${err}" ]] && err="$(awk -F'|' '{print $3}' <<< "${sacct_line}")"
    fi
  fi

  printf '%s\t%s\n' "${out}" "${err}"
}

resolve_job_status_from_slurm() {
  local job_id="$1"
  local squeue_line=""
  local sacct_line=""
  local state=""
  local exit_code="-"
  local finished_at="-"

  squeue_line="$(run_remote_bash "squeue -h -j ${job_id} -o '%T|%M|%R' 2>/dev/null" | tail -n 1 || true)"
  if [[ -n "${squeue_line}" ]]; then
    state="$(awk -F'|' '{print $1}' <<< "${squeue_line}")"
  fi

  sacct_line="$(run_remote_bash "sacct -n -P -j ${job_id} --format=JobIDRaw,State,ExitCode,End 2>/dev/null" \
    | awk -F'|' -v id="${job_id}" '$1 == id {print $0; exit}' || true)"
  if [[ -n "${sacct_line}" ]]; then
    [[ -z "${state}" ]] && state="$(awk -F'|' '{print $2}' <<< "${sacct_line}")"
    exit_code="$(awk -F'|' '{print $3}' <<< "${sacct_line}")"
    finished_at="$(awk -F'|' '{print $4}' <<< "${sacct_line}")"
  fi

  [[ -n "${state}" ]] || state="UNKNOWN"
  case "${finished_at}" in
    ""|Unknown|N/A|None|NONE)
      finished_at="-"
      ;;
  esac

  printf '%s\t%s\t%s\n' "${state}" "${exit_code:-"-"}" "${finished_at}"
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

resolve_remote_paths() {
  local job_id="$1"
  local sbatch_file="$2"
  local job_name="$3"
  local out=""
  local err=""
  local out_template=""
  local err_template=""

  read -r out err < <(resolve_remote_paths_from_slurm "${job_id}")

  if [[ -n "${out}" && "${out}" == *%* ]]; then
    out="$(materialize_template "${out}" "${job_id}" "${job_name}")"
  fi
  if [[ -n "${err}" && "${err}" == *%* ]]; then
    err="$(materialize_template "${err}" "${job_id}" "${job_name}")"
  fi

  if [[ -z "${out}" || -z "${err}" ]]; then
    if [[ -n "${sbatch_file}" && -r "${sbatch_file}" ]]; then
      out_template="$(sbatch_directive_value "${sbatch_file}" "-o" "--output" || true)"
      err_template="$(sbatch_directive_value "${sbatch_file}" "-e" "--error" || true)"
      [[ -n "${out_template}" ]] || out_template="slurm-%j.out"
      [[ -n "${err_template}" ]] || err_template="${out_template}"
      [[ -z "${out}" ]] && out="$(materialize_template "${out_template}" "${job_id}" "${job_name}")"
      [[ -z "${err}" ]] && err="$(materialize_template "${err_template}" "${job_id}" "${job_name}")"
    else
      [[ -z "${out}" ]] && out="slurm-${job_id}.out"
      [[ -z "${err}" ]] && err="${out}"
    fi
  fi

  printf '%s\t%s\n' "${out}" "${err}"
}

job_ref="${1:-last}"
if [[ "${job_ref}" == "-h" || "${job_ref}" == "--help" || "${job_ref}" == "help" ]]; then
  usage
  exit 0
fi
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

job_id="$(resolve_job_id "${job_ref}" || true)"
[[ -n "${job_id}" ]] || die "could not resolve job id (registry and ${OUT_ROOT} are empty)"

job_dir="${OUT_ROOT}/${job_id}"
mkdir -p "${job_dir}"

registry_row="$("${SCRIPT_DIR}/job_registry.sh" find "${job_id}" || true)"
sbatch_file="$(row_field "${registry_row}" 3)"
job_name="$(row_field "${registry_row}" 4)"

job_meta="${job_dir}/job.meta"
if [[ -f "${job_meta}" ]]; then
  [[ -z "${sbatch_file}" ]] && sbatch_file="$(meta_field "${job_meta}" "sbatch_file" || true)"
  [[ -z "${job_name}" ]] && job_name="$(meta_field "${job_meta}" "job_name" || true)"
fi

if [[ -z "${job_name}" && -n "${sbatch_file}" && -r "${sbatch_file}" ]]; then
  job_name="$(sbatch_directive_value "${sbatch_file}" "-J" "--job-name" || true)"
fi
[[ -n "${job_name}" ]] || job_name="job_${job_id}"

poll_state=""
poll_exit="-"
poll_finished_at="-"
read -r poll_state poll_exit poll_finished_at < <(resolve_job_status_from_slurm "${job_id}")
if [[ -n "${registry_row}" ]]; then
  "${SCRIPT_DIR}/job_registry.sh" status "${job_id}" "${poll_state}" "${poll_exit:-"-"}" "${poll_finished_at:-"-"}"
  "${SCRIPT_DIR}/job_registry.sh" polled "${job_id}"
fi

local_out="$(find_log_file "${job_dir}" "out" || true)"
local_err="$(find_log_file "${job_dir}" "err" || true)"

remote_out=""
remote_err=""
refresh_login=""
refreshed_stdout=0

if [[ -n "${local_out}" && -n "${local_err}" ]]; then
  read -r remote_out remote_err < <(resolve_remote_paths "${job_id}" "${sbatch_file}" "${job_name}")
  refresh_login="$(resolve_login 2>/dev/null || true)"
  if [[ -n "${refresh_login}" ]]; then
    if [[ -n "${remote_out}" ]]; then
      if "${SCRIPT_DIR}/hpc_rsync.sh" -az "${refresh_login}:${remote_out}" "${job_dir}/" >/dev/null 2>&1; then
        local_out="${job_dir}/$(basename "${remote_out}")"
        refreshed_stdout=1
      else
        echo "warn: could not refresh stdout from ${refresh_login}:${remote_out}; using existing local copy" >&2
      fi
    fi

    if [[ -n "${remote_err}" ]]; then
      if [[ "${remote_err}" == "${remote_out}" ]]; then
        if [[ "${refreshed_stdout}" == "1" ]]; then
          local_err="${local_out}"
        fi
      elif "${SCRIPT_DIR}/hpc_rsync.sh" -az "${refresh_login}:${remote_err}" "${job_dir}/" >/dev/null 2>&1; then
        local_err="${job_dir}/$(basename "${remote_err}")"
      else
        echo "warn: could not refresh stderr from ${refresh_login}:${remote_err}; using existing local copy" >&2
      fi
    fi
  fi
fi

if [[ -z "${local_out}" || -z "${local_err}" ]]; then
  read -r remote_out remote_err < <(resolve_remote_paths "${job_id}" "${sbatch_file}" "${job_name}")

  login="$(resolve_login)"

  if [[ -z "${local_out}" ]]; then
    [[ -n "${remote_out}" ]] || die "missing stdout locally and could not resolve remote stdout path"
    echo "Fetching stdout from ${login}:${remote_out}"
    "${SCRIPT_DIR}/hpc_rsync.sh" -az "${login}:${remote_out}" "${job_dir}/"
    local_out="${job_dir}/$(basename "${remote_out}")"
  fi

  if [[ -z "${local_err}" ]]; then
    [[ -n "${remote_err}" ]] || die "missing stderr locally and could not resolve remote stderr path"
    if [[ "${remote_err}" == "${remote_out}" ]]; then
      local_err="${local_out}"
    else
      echo "Fetching stderr from ${login}:${remote_err}"
      "${SCRIPT_DIR}/hpc_rsync.sh" -az "${login}:${remote_err}" "${job_dir}/"
      local_err="${job_dir}/$(basename "${remote_err}")"
    fi
  fi
fi

[[ -f "${local_out}" ]] || die "stdout file not found for job ${job_id}"
[[ -f "${local_err}" ]] || die "stderr file not found for job ${job_id}"

canonical_out="${job_dir}/std.out"
canonical_err="${job_dir}/std.err"

if [[ "${local_out}" != "${canonical_out}" ]]; then
  cp -f "${local_out}" "${canonical_out}"
fi
if [[ "${local_err}" != "${canonical_err}" ]]; then
  cp -f "${local_err}" "${canonical_err}"
fi

echo "job_id=${job_id}"
echo "registry_state=${poll_state}"
echo "registry_exit_code=${poll_exit:-"-"}"
echo "registry_finished_at=${poll_finished_at:-"-"}"
if [[ -n "${remote_out}" || -n "${remote_err}" ]]; then
  echo "remote_stdout=${remote_out:-unknown}"
  echo "remote_stderr=${remote_err:-unknown}"
fi
echo "local_stdout=${canonical_out}"
echo "local_stderr=${canonical_err}"
echo
echo "===== STDOUT (${job_id}) ====="
cat "${canonical_out}"
echo

if [[ -t 0 ]]; then
  printf 'Show stderr for job %s? [y/N] ' "${job_id}"
  read -r show_stderr
else
  show_stderr=""
fi

if [[ "${show_stderr}" =~ ^([yY]|[yY][eE][sS])$ ]]; then
  echo
  echo "===== STDERR (${job_id}) ====="
  cat "${canonical_err}"
fi
