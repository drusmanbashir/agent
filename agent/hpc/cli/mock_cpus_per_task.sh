#!/bin/bash
#SBATCH -J mock_cpus_per_task
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -p gpushort
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:1
#SBATCH -t 0:01:00
#SBATCH --mem-per-cpu=7680M
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

threads="${SLURM_CPUS_PER_TASK:-${SLURM_NTASKS:-1}}"
export OMP_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS="${threads}"
export MKL_NUM_THREADS="${threads}"
export NUMEXPR_NUM_THREADS="${threads}"

echo "host=$(hostname)"
echo "job_id=${SLURM_JOB_ID:-}"
echo "ntasks=${SLURM_NTASKS:-}"
echo "cpus_per_task=${SLURM_CPUS_PER_TASK:-}"
echo "omp_num_threads=${OMP_NUM_THREADS}"
echo "pwd=$(pwd)"
echo "start_ts=$(date -Iseconds)"
sleep 2
echo "end_ts=$(date -Iseconds)"
