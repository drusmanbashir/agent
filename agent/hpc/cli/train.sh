#!/bin/bash
#SBATCH -n 12
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

python -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/training/train_retry.py \
  --project "$t" \
  --plan-num "$p" \
  --fold "$f" \
  --epochs 500 \
  --compiled false \
  --profiler false \
  --wandb true \
  --cache-rate 0.0 \
  --bsf true \
  --train-indices "$i" \
  --val-every-n-epochs "$v" \
  --learning-rate "$l" \
  --run-name "$r"
