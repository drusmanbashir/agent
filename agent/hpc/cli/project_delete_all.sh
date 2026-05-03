#!/bin/bash
#SBATCH -J proj_delete_all
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 1
#SBATCH -t 0:15:00
#SBATCH --mem=4G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl

for t in "$@"; do
  python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project/project_delete.py -t "$t"
done
