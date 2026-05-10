#!/bin/bash
#SBATCH -J proj_delete_all
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 1
#SBATCH --cpus-per-task=16
#SBATCH -t 0:15:00
#SBATCH --mem=4G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: project_delete_all.sh [project_title ...] [-c <cpus_per_task>]
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

cpus_per_task="16"
projects=()
while [[ $# -gt 0 ]]; do
  case "$1" in
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      projects+=("$1")
      shift
      ;;
  esac
done

if ! [[ "${cpus_per_task}" =~ ^[0-9]+$ ]] || [[ "${cpus_per_task}" -lt 1 ]]; then
  echo "cpus_per_task must be a positive integer, got: ${cpus_per_task}" >&2
  exit 2
fi

for t in "${projects[@]}"; do
  python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project/project_delete.py -t "$t"
done
