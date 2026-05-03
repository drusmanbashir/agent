#!/bin/bash
#SBATCH -J datasource_init
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 1
#SBATCH -t 3:00:00
#SBATCH --mem-per-cpu=8G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: datasource.sh <folder> <name> [-n <num_processes>]
EOF
}

module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl
export FRAN_STORE_LABEL_STATS="${FRAN_STORE_LABEL_STATS:-0}"
export FRAN_STORE_GIFS="${FRAN_STORE_GIFS:-0}"

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi

f="$1"
m="$2"
shift 2

n="1"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num-processes)
      n="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

python /data/EECS-LITQ/fran_storage/code/fran/fran/run/project/datasource_init.py "$f" "$m" -n "$n"
