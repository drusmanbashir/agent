#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CALLER_CWD="$(pwd)"

SBATCH_FILE="${1:?Usage: scripts/hpc_sbatch.sh scripts/project.sh [script args...]}"
shift
if [[ "${SBATCH_FILE}" != /* ]]; then
  SBATCH_FILE="${CALLER_CWD}/${SBATCH_FILE}"
fi

cd "${REPO_ROOT}"

REMOTE_DIR="${HPC_SBATCH_REMOTE_DIR:-.hpc_agent/sbatch}"
POLL_SECONDS="${HPC_SBATCH_POLL_SECONDS:-15}"
LOGIN="${HPC_LOGIN:-$(python -m tools.cli load_pwd --field login)}"

base_name="$(basename "${SBATCH_FILE}")"
remote_dir_q="$(printf "%q" "${REMOTE_DIR}")"
remote_template_q="$(printf "%q" "${REMOTE_DIR}/${base_name%.sh}.XXXXXX.sh")"

remote_script="$("${SCRIPT_DIR}/hpc_ssh.sh" "mkdir -p ${remote_dir_q} && mktemp ${remote_template_q}" | tail -n 1)"
"${SCRIPT_DIR}/hpc_rsync.sh" -az "${SBATCH_FILE}" "${LOGIN}:${remote_script}" >/dev/null

remote_script_q="$(printf "%q" "${remote_script}")"
poll_seconds_q="$(printf "%q" "${POLL_SECONDS}")"
script_args_q=()
for arg in "$@"; do
  script_args_q+=("$(printf "%q" "${arg}")")
done

read -r -d '' remote_inner <<EOF || true
set -euo pipefail
chmod +x ${remote_script_q}
job_id="\$(sbatch --parsable ${remote_script_q} ${script_args_q[*]} | awk -F';' '{print \$1}')"
echo "Submitted batch job \${job_id}"
poll_seconds=${poll_seconds_q}

while true; do
  queue_state="\$(squeue -h -j "\${job_id}" -o '%T' 2>/dev/null | head -n 1 || true)"
  if [[ -n "\${queue_state}" ]]; then
    echo "[\$(date +%H:%M:%S)] \${job_id} \${queue_state}"
    sleep "\${poll_seconds}"
    continue
  fi

  final_state=""
  final_exit=""
  if command -v sacct >/dev/null 2>&1; then
    final="\$(sacct -n -P -j "\${job_id}" --format=JobIDRaw,State,ExitCode 2>/dev/null | awk -F'|' -v id="\${job_id}" '\$1 == id {print \$2 "|" \$3; exit}')"
    final_state="\${final%%|*}"
    final_exit="\${final#*|}"
  fi

  if [[ -n "\${final_state}" ]]; then
    echo "[\$(date +%H:%M:%S)] \${job_id} \${final_state} \${final_exit}"
    [[ "\${final_state}" == COMPLETED* ]]
    exit \$?
  fi

  echo "[\$(date +%H:%M:%S)] \${job_id} no longer in queue"
  exit 0
done
EOF

remote_cmd="bash -lc $(printf "%q" "${remote_inner}")"
"${SCRIPT_DIR}/hpc_ssh.sh" "${remote_cmd}"
