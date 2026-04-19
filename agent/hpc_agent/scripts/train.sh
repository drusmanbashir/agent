#!/bin/bash
#SBATCH --ntasks-per-node=12
#SBATCH -p andrena
#SBATCH -A pilot_andrena
#SBATCH --mem-per-cpu=7500M
#SBATCH --gres=gpu:1
#SBATCH -t 20:0:0
#SBATCH -J training
#SBATCH -o %x.o%j
#SBATCH -e %x.e%j

module load miniforge
conda activate dl

echo ${SLURM_ARRAY_TASK_ID}

project_title="${1:-kits}"
plan="${2:-8}"
fold="${3:-1}"
lr="${4:-}"
train_indices="${5:-}"
val_every_n_epochs="${6:-5}"

python -u /data/EECS-LITQ/fran_storage/code/fran/fran/run/train_retry.py \
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
${lr:+--learning-rate "$lr"}

