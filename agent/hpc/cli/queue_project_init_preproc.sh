#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HPC_SSH="${SCRIPT_DIR}/hpc_ssh.sh"
JOB_REGISTRY="${SCRIPT_DIR}/job_registry.sh"

LOGIN=""
if [[ "${1:-}" == "--login" ]]; then
  LOGIN="${2:-}"
  shift 2
fi

if [[ $# -lt 4 ]]; then
  echo "Usage: $(basename "$0") [--login user@host] <project_title> <mnemonic> <plan_num> <datasource...> [-n <num_processes>] [-c <cpus_per_task>]" >&2
  exit 2
fi

PROJECT_TITLE="$1"
if [[ "${PROJECT_TITLE}" == "litsmc" ]]; then
  PROJECT_TITLE="lits"
fi
MNEMONIC="$2"
PLAN_NUM="$3"
shift 3
NPROC="1"
CPUS_PER_TASK="16"
DATASOURCES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num-processes)
      NPROC="$2"
      shift 2
      ;;
    -c|--cpus-per-task)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      CPUS_PER_TASK="$2"
      shift 2
      ;;
    -c=*|--cpus-per-task=*)
      CPUS_PER_TASK="${1#*=}"
      shift
      ;;
    *)
      DATASOURCES+=("$1")
      shift
      ;;
  esac
done

if ! [[ "${CPUS_PER_TASK}" =~ ^[0-9]+$ ]] || [[ "${CPUS_PER_TASK}" -lt 1 ]]; then
  echo "cpus_per_task must be a positive integer, got: ${CPUS_PER_TASK}" >&2
  exit 2
fi

REMOTE_SCRIPT="$(mktemp)"
trap 'rm -f "${REMOTE_SCRIPT}"' EXIT

cat > "${REMOTE_SCRIPT}" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

PROJECT_TITLE="$1"
if [[ "${PROJECT_TITLE}" == "litsmc" ]]; then
  PROJECT_TITLE="lits"
fi
MNEMONIC="$2"
PLAN_NUM="$3"
NPROC="$4"
CPUS_PER_TASK="$5"
shift 5
DATASOURCES=("$@")

LOG_DIR="/data/EECS-LITQ/fran_storage/logs"
FRAN_CONF_DIR="/data/EECS-LITQ/fran_storage/conf"
FRAN_CODE_ROOT="/data/EECS-LITQ/fran_storage/code"
PROJECT_INIT_PY="/data/EECS-LITQ/fran_storage/code/fran/fran/run/project/project_init.py"
PREPROC_PY="/data/EECS-LITQ/fran_storage/code/fran/fran/run/preproc/analyze_resample.py"
PYTHONPATH_EXPORT="export PYTHONPATH=${FRAN_CODE_ROOT}/localiser:${FRAN_CODE_ROOT}/fran:${FRAN_CODE_ROOT}/utilz:${FRAN_CODE_ROOT}/label_analysis:\${PYTHONPATH:-}"
POSTPROC_EXPORTS="export FRAN_STORE_LABEL_STATS=0; export FRAN_STORE_GIFS=0"
THREAD_EXPORTS="threads=\${SLURM_CPUS_PER_TASK:-\${SLURM_NTASKS:-1}}; export OMP_NUM_THREADS=\${threads}; export OPENBLAS_NUM_THREADS=\${threads}; export MKL_NUM_THREADS=\${threads}; export NUMEXPR_NUM_THREADS=\${threads}"

printf -v DS_ARGS '%q ' "${DATASOURCES[@]}"
INIT_CMD="module load miniforge; source \"\$(conda info --base)/etc/profile.d/conda.sh\"; conda activate dl; export FRAN_CONF=${FRAN_CONF_DIR}; ${PYTHONPATH_EXPORT}; ${POSTPROC_EXPORTS}; ${THREAD_EXPORTS}; python ${PROJECT_INIT_PY} -t ${PROJECT_TITLE} -m ${MNEMONIC} --datasources ${DS_ARGS}-n ${NPROC}"
PREPROC_CMD="module load miniforge; source \"\$(conda info --base)/etc/profile.d/conda.sh\"; conda activate dl; export FRAN_CONF=${FRAN_CONF_DIR}; ${PYTHONPATH_EXPORT}; ${POSTPROC_EXPORTS}; ${THREAD_EXPORTS}; python -u ${PREPROC_PY} -t ${PROJECT_TITLE} -p ${PLAN_NUM} -n ${NPROC}"

JID_INIT="$(
  sbatch --parsable \
    -J "proj_init_${PROJECT_TITLE}" \
    -D "${LOG_DIR}" \
    -p compute \
    -n "${NPROC}" \
    --cpus-per-task="${CPUS_PER_TASK}" \
    -t 3:00:00 \
    --mem-per-cpu=8G \
    -o "${LOG_DIR}/%x-%j.out" \
    -e "${LOG_DIR}/%x-%j.err" \
    --wrap "${INIT_CMD}" | awk -F';' '{print $1}'
)"

JID_PREPROC="$(
  sbatch --parsable \
    --dependency="afterok:${JID_INIT}" \
    -J "preproc_${PROJECT_TITLE}_p${PLAN_NUM}" \
    -D "${LOG_DIR}" \
    -p compute \
    -n "${NPROC}" \
    --cpus-per-task="${CPUS_PER_TASK}" \
    -t 5:00:00 \
    --mem-per-cpu=7500M \
    --mail-type=NONE \
    -o "${LOG_DIR}/%x-%j.out" \
    -e "${LOG_DIR}/%x-%j.err" \
    --wrap "${PREPROC_CMD}" | awk -F';' '{print $1}'
)"

echo "queued_init_job=${JID_INIT}"
echo "queued_preproc_job=${JID_PREPROC}"
echo "dependency=afterok:${JID_INIT}"
SH

HPC_ARGS=()
if [[ -n "${LOGIN}" ]]; then
  HPC_ARGS+=(--login "${LOGIN}")
fi

submit_output="$("${HPC_SSH}" "${HPC_ARGS[@]}" --script "${REMOTE_SCRIPT}" -- "${PROJECT_TITLE}" "${MNEMONIC}" "${PLAN_NUM}" "${NPROC}" "${CPUS_PER_TASK}" "${DATASOURCES[@]}")"
printf '%s\n' "${submit_output}"

jid_init="$(printf '%s\n' "${submit_output}" | awk -F'=' '/^queued_init_job=/ {print $2; exit}')"
jid_preproc="$(printf '%s\n' "${submit_output}" | awk -F'=' '/^queued_preproc_job=/ {print $2; exit}')"

if [[ -n "${jid_init}" ]]; then
  "${JOB_REGISTRY}" submit "${jid_init}" "${SCRIPT_DIR}/queue_project_init_preproc.sh" "proj_init_${PROJECT_TITLE}" "stdin:${REMOTE_SCRIPT}"
fi

if [[ -n "${jid_preproc}" ]]; then
  "${JOB_REGISTRY}" submit "${jid_preproc}" "${SCRIPT_DIR}/queue_project_init_preproc.sh" "preproc_${PROJECT_TITLE}_p${PLAN_NUM}" "stdin:${REMOTE_SCRIPT}"
fi
