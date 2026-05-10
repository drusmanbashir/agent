#!/bin/bash
#SBATCH -J project_init
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 1
#SBATCH --cpus-per-task=16
#SBATCH -t 3:00:00
#SBATCH --mem-per-cpu=8G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: project_init.sh <project_title> <mnemonic> [datasource ...] [-n <num_processes>] [-c <cpus_per_task>] [--test]
EOF
}

threads="${SLURM_CPUS_PER_TASK:-${SLURM_NTASKS:-1}}"
export OMP_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS="${threads}"
export MKL_NUM_THREADS="${threads}"
export NUMEXPR_NUM_THREADS="${threads}"
module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl
export FRAN_STORE_LABEL_STATS="${FRAN_STORE_LABEL_STATS:-0}"
export FRAN_STORE_GIFS="${FRAN_STORE_GIFS:-0}"

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi

title="$1"
mnemonic="$2"
shift 2

n="1"
cpus_per_task="16"
test_flag=""
datasources=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num-processes)
      n="$2"
      shift 2
      ;;
    -c|--cpus-per-task)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        usage >&2
        exit 2
      fi
      cpus_per_task="$2"
      shift 2
      ;;
    -c=*|--cpus-per-task=*)
      cpus_per_task="${1#*=}"
      shift
      ;;
    --test)
      test_flag="--test"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      datasources+=("$1")
      shift
      ;;
  esac
done

if ! [[ "${cpus_per_task}" =~ ^[0-9]+$ ]] || [[ "${cpus_per_task}" -lt 1 ]]; then
  echo "cpus_per_task must be a positive integer, got: ${cpus_per_task}" >&2
  exit 2
fi

cmd=(
  python
  /data/EECS-LITQ/fran_storage/code/fran/fran/run/project/project_init.py
  -t "$title"
  -m "$mnemonic"
  -n "$n"
)

if [[ ${#datasources[@]} -gt 0 ]]; then
  cmd+=(--datasources "${datasources[@]}")
fi

if [[ -n "$test_flag" ]]; then
  cmd+=("$test_flag")
fi

"${cmd[@]}"
