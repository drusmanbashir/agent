#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH -p andrena
#SBATCH -A pilot_andrena
#SBATCH --mem-per-cpu=7500M
#SBATCH --gres=gpu:1
#SBATCH -t 20:0:0
#SBATCH -J training
#SBATCH -o %x.o%j
#SBATCH -e %x.e%j

set -euo pipefail

module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl

t="$1"
p="$2"
f="$3"
l="$4"
i="$5"
v="$6"
r="$7"

epochs=500
wandb=true
bsf=true

for kv in "${@:8}"; do
  case "$kv" in
    epochs=*) epochs="${kv#*=}" ;;
    wandb=*) wandb="${kv#*=}" ;;
    bsf=*) bsf="${kv#*=}" ;;
    *)
      printf 'Usage error: unknown override "%s". Allowed keys: epochs, wandb, bsf\n' "$kv" >&2
      exit 2
      ;;
  esac
done

THREADS="${SLURM_CPUS_PER_TASK:-${SLURM_NTASKS:-1}}"
export OMP_NUM_THREADS="${THREADS}"
export OPENBLAS_NUM_THREADS="${THREADS}"
export MKL_NUM_THREADS="${THREADS}"
export NUMEXPR_NUM_THREADS="${THREADS}"

cmd=(
  python -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/training/train_retry.py
  --project "$t"
  --plan-num "$p"
  --fold "$f"
  --epochs "$epochs"
  --compiled false
  --profiler false
  --wandb "$wandb"
  --cache-rate 0.0
  --bsf "$bsf"
  --train-indices "$i"
  --val-every-n-epochs "$v"
  --learning-rate "$l"

)

if [[ -n "${r}" && "${r}" != "none" && "${r}" != "null" ]]; then
  cmd+=(--run-name "$r")
fi

"${cmd[@]}"
