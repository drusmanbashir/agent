#!/bin/bash
#SBATCH -J fran_preproc
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 16
#SBATCH -t 3:00:00
#SBATCH --mem-per-cpu=8G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

 module load miniforge
 source "$(conda info --base)/etc/profile.d/conda.sh"
 conda activate dl

python /data/EECS-LITQ/fran_storage/code/fran/fran/run/analyze_resample.py -t totalseg -p 0 -n 4

#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/analyze_resample.py -t kits2 -p 8 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t kitstmp  -m kidneys --datasources kits23 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t totalseg  -m totalseg --datasources totalseg -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/analyze_resample.py -t totalgseg -p 2 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t nodes -m nodes --datasources nodes nodesthick -n 1
#
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t totalseg  -m totalseg --datasources totalseg -n 4

#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t colon  -m colon --datasources colonmsd10 -n 4
#python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_init.py -t lidc  -m lidc --datasources lidc -n 4


