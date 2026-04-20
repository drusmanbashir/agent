#!/bin/bash
module load miniforge
conda activate dl

project_title="${1:-kits}"
plan="${2:-4}"
fold="${3:-0}"
lr="${4:-}"
train_indices="${5:-200}"
val_every_n_epochs="${6:-5}"
run_name="${7:-}"
extra_args=()

[[ -n "$lr" ]] && extra_args+=(--learning-rate "$lr")
[[ -n "$run_name" ]] && extra_args+=(--run-name "$run_name")

python /data/EECS-LITQ/fran_storage/code/fran/fran/run/train.py \
--project "$project_title" \
--plan-num "$plan" \
--fold "$fold" \
--epochs 500 \
--compiled false \
--profiler false \
--wandb true \
--cache-rate 0.0 \
--bsf true \
--train-indices "$train_indices" \
--val-every-n-epochs "$val_every_n_epochs" \
"${extra_args[@]}"
