#!/bin/bash
#SBATCH -J fran_preproc
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -p highmem
#SBATCH -n 1
#SBATCH --cpus-per-task=16
#SBATCH -t 5:00:00
#SBATCH --mem=128G
#SBATCH --mail-type=NONE
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

FRAN_REMOTE_ROOT="/data/EECS-LITQ/fran_storage"
FRAN_CONF_DIR="${FRAN_REMOTE_ROOT}/conf"
FRAN_CODE_ROOT="${FRAN_REMOTE_ROOT}/code"
FRAN_REPO_ROOT="${FRAN_CODE_ROOT}/fran"
LOCALISER_REPO_ROOT="${FRAN_CODE_ROOT}/localiser"
UTILZ_REPO_ROOT="${FRAN_CODE_ROOT}/utilz"
LABEL_ANALYSIS_REPO_ROOT="${FRAN_CODE_ROOT}/label_analysis"

usage() {
  cat <<'EOF'
Usage: preproc.sh <project_title> <plan_num> [-n <num_processes_and_cpus>] [-c <compat_num_processes_and_cpus>]
EOF
}

log_fail_context() {
  local exit_code="$1"
  local failed_cmd="$2"
  local ts
  ts="$(date -Iseconds)"
  echo "preproc_fail_ts=${ts} exit_code=${exit_code} failed_cmd=${failed_cmd}" >&2
}

trap 'rc=$?; log_fail_context "${rc}" "${BASH_COMMAND}"; exit "${rc}"' ERR

threads="${SLURM_CPUS_PER_TASK:-${SLURM_NTASKS:-1}}"
export OMP_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS="${threads}"
export MKL_NUM_THREADS="${threads}"
export NUMEXPR_NUM_THREADS="${threads}"
module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl
export FRAN_CONF="${FRAN_CONF_DIR}"
export PYTHONPATH="${LOCALISER_REPO_ROOT}:${FRAN_REPO_ROOT}:${UTILZ_REPO_ROOT}:${LABEL_ANALYSIS_REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export FRAN_STORE_LABEL_STATS="${FRAN_STORE_LABEL_STATS:-0}"
export FRAN_STORE_GIFS="${FRAN_STORE_GIFS:-0}"

echo "host=$(hostname)"
echo "job_id=${SLURM_JOB_ID}"
echo "partition=${SLURM_JOB_PARTITION}"
echo "ntasks=${SLURM_NTASKS}"
echo "cpus_per_task=${SLURM_CPUS_PER_TASK:-}"
echo "python=$(command -v python)"
echo "FRAN_CONF=${FRAN_CONF}"
echo "PYTHONPATH=${PYTHONPATH}"
echo "FRAN_STORE_LABEL_STATS=${FRAN_STORE_LABEL_STATS}"
echo "FRAN_STORE_GIFS=${FRAN_STORE_GIFS}"
echo "OMP_NUM_THREADS=${OMP_NUM_THREADS}"

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi

t="$1"
if [[ "${t}" == "litsmc" ]]; then
  t="lits"
fi
p="$2"
shift 2

n="16"
cpus_per_task="16"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num-processes)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        usage >&2
        exit 2
      fi
      n="$2"
      cpus_per_task="$2"
      shift 2
      ;;
    -c|--cpus-per-task)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        usage >&2
        exit 2
      fi
      n="$2"
      cpus_per_task="$2"
      shift 2
      ;;
    -c=*|--cpus-per-task=*)
      n="${1#*=}"
      cpus_per_task="${1#*=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "${n}" =~ ^[0-9]+$ ]] || [[ "${n}" -lt 1 ]]; then
  echo "num_processes must be a positive integer, got: ${n}" >&2
  exit 2
fi

if ! [[ "${cpus_per_task}" =~ ^[0-9]+$ ]] || [[ "${cpus_per_task}" -lt 1 ]]; then
  echo "cpus_per_task must be a positive integer, got: ${cpus_per_task}" >&2
  exit 2
fi

echo "preproc_start_ts=$(date -Iseconds)"
echo "preproc_cpus_per_task=${cpus_per_task}"
echo "preproc_cmd=python -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/preproc/analyze_resample.py -t ${t} -p ${p} -n ${n}"

python -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/preproc/analyze_resample.py -t "$t" -p "$p" -n "$n"
