#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH -p andrena
#SBATCH -A pilot_andrena
#SBATCH --mem-per-cpu=7500M
#SBATCH --gres=gpu:1
#SBATCH -t 40:0:0
#SBATCH -J training
#SBATCH -o %x.o%j
#SBATCH -e %x.e%j

set -euo pipefail

THREADS="${SLURM_CPUS_PER_TASK:-${SLURM_NTASKS:-1}}"
export OMP_NUM_THREADS="${THREADS}"
export OPENBLAS_NUM_THREADS="${THREADS}"
export MKL_NUM_THREADS="${THREADS}"
export NUMEXPR_NUM_THREADS="${THREADS}"

module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl

PROJECT="${1:-kits23}"
PLAN_NUM="${2:-7}"
DEVICES="${3:-1}"
BS="${4:-4}"
EPOCHS="${5:-500}"
FOLD="${6:-0}"
VAL_DEVICE="${7:-cuda}"
COMPILED="${8:-false}"
PROFILER="${9:-false}"
WANDB="${10:-true}"
CACHE_RATE="${11:-0.0}"
LR="${12:-}"
RUN_NAME="${13:-}"
DESCRIPTION="${14:-}"
DS_TYPE="${15:-}"
ALL="${16:-false}"
VAL_EVERY_N_EPOCHS="${17:-2}"
TRAIN_INDICES="${18:-}"
BSF="${19:-true}"
DUAL_SSD="${20:-false}"
MAX_RETRIES="${21:-3}"
STEP="${22:-1}"
MIN_BS="${23:-1}"
PYTHON_BIN="${24:-python}"
BATCH_TFMS="${25:-false}"

cmd=(
  "$PYTHON_BIN" -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/training/train_retry.py
  --project "$PROJECT"
  --plan-num "$PLAN_NUM"
  --devices "$DEVICES"
  --bs "$BS"
  --fold "$FOLD"
  --epochs "$EPOCHS"
  --compiled "$COMPILED"
  --profiler "$PROFILER"
  --wandb "$WANDB"
  --cache-rate "$CACHE_RATE"
  --bsf "$BSF"
  --batch-tfms "$BATCH_TFMS"
  --val-every-n-epochs "$VAL_EVERY_N_EPOCHS"
  --val-device "$VAL_DEVICE"
  --all "$ALL"
  --dual-ssd "$DUAL_SSD"
  --max-retries "$MAX_RETRIES"
  --step "$STEP"
  --min-bs "$MIN_BS"
)

if [[ -n "$LR" ]]; then
  cmd+=(--learning-rate "$LR")
fi
if [[ -n "$RUN_NAME" && "$RUN_NAME" != "none" && "$RUN_NAME" != "null" ]]; then
  cmd+=(--run-name "$RUN_NAME")
fi
if [[ -n "$DESCRIPTION" ]]; then
  cmd+=(--description "$DESCRIPTION")
fi
if [[ -n "$DS_TYPE" ]]; then
  cmd+=(--ds-type "$DS_TYPE")
fi
if [[ -n "$TRAIN_INDICES" && "$TRAIN_INDICES" != "none" && "$TRAIN_INDICES" != "null" ]]; then
  cmd+=(--train-indices "$TRAIN_INDICES")
fi

"${cmd[@]}"
