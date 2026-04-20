#!/bin/bash
#SBATCH -J proj_delete
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

project_title="${PROJECT_TITLE:-}"
positionals=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--project-title|--title|--project)
      project_title="$2"
      shift 2
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

[[ ${#positionals[@]} -ge 1 ]] && project_title="${positionals[0]}"

if [[ -z "${project_title}" ]]; then
  echo "Usage: $0 <project_title>" >&2
  echo "       PROJECT_TITLE=<project_title> $0" >&2
  exit 2
fi

python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project_delete.py \
  -t "$project_title"
