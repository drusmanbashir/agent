#!/bin/bash
#SBATCH -J fran_preproc
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -p andrena
#SBATCH -A pilot_andrena
#SBATCH -n 12
#SBATCH -t 5:00:00
#SBATCH --mem-per-cpu=7500M
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

if ! command -v module >/dev/null 2>&1; then
  [[ -r /etc/profile.d/modules.sh ]] && source /etc/profile.d/modules.sh
fi

module load miniforge
conda activate dl

echo "host=$(hostname)"
echo "job_id=${SLURM_JOB_ID:-}"
echo "partition=${SLURM_JOB_PARTITION:-}"
echo "ntasks=${SLURM_NTASKS:-}"
echo "python=$(command -v python)"
python - <<'PY'
import fran
print(f"fran={fran.__file__}")
PY

project_title="${PROJECT_TITLE:-kits}"
plan="${PLAN:-0}"
num_workers="${NUM_WORKERS:-${SLURM_NTASKS:-4}}"
positionals=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--project-title|--title)
      project_title="$2"
      shift 2
      ;;
    -p|--plan|--plan-num)
      plan="$2"
      shift 2
      ;;
    -n|--num-workers)
      num_workers="$2"
      shift 2
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

[[ ${#positionals[@]} -ge 1 ]] && project_title="${positionals[0]}"
[[ ${#positionals[@]} -ge 2 ]] && plan="${positionals[1]}"
[[ ${#positionals[@]} -ge 3 ]] && num_workers="${positionals[2]}"
num_workers="${num_workers:-4}"

if [[ "${PREPROC_TRACE_ONLY:-0}" == "1" ]]; then
  echo "PREPROC_TRACE_ONLY=1; skipping analyze_resample"
  exit 0
fi

python -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/analyze_resample.py \
  -t "$project_title" \
  -p "$plan" \
  -n "$num_workers"

#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/analyze_resample.py -t kits2 -p 8 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t totalseg  -m totalseg --datasources totalseg -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/analyze_resample.py -t totalgseg -p 2 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t nodes -m nodes --datasources nodes nodesthick -n 1
#
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t totalseg  -m totalseg --datasources totalseg -n 4

#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t colon  -m colon --datasources colonmsd10 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t lidc  -m lidc --datasources lidc -n 4
