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

project_titles=()
read -r -a env_project_titles <<< "${PROJECT_TITLES:-}"
project_titles+=("${env_project_titles[@]}")

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--project-title|--title|--project)
      project_titles+=("$2")
      shift 2
      ;;
    --projects)
      shift
      while [[ $# -gt 0 && "$1" != -* ]]; do
        project_titles+=("$1")
        shift
      done
      ;;
    *)
      project_titles+=("$1")
      shift
      ;;
  esac
done

if [[ ${#project_titles[@]} -eq 0 ]]; then
  echo "Usage: $0 <project_title> [project_title ...]" >&2
  echo "       $0 --projects <project_title> [project_title ...]" >&2
  echo "       PROJECT_TITLES='proj1 proj2' $0" >&2
  exit 2
fi

for project_title in "${project_titles[@]}"; do
  echo "Deleting project: ${project_title}"
  python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_delete.py \
    -t "$project_title"
done
