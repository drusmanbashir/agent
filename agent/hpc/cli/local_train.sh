#!/bin/bash
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

python /data/EECS-LITQ/fran_storage/code/fran/fran/run/training/train.py \
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
