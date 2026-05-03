#!/bin/bash
#SBATCH -J datasource_update
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 1
#SBATCH -t 3:00:00
#SBATCH --mem-per-cpu=8G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: datasource_update.sh <folder> <name> [-n <num_processes>] [--dry-run] [--return-voxels]
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
d="0"
r="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num-processes)
      n="$2"
      shift 2
      ;;
    --dry-run)
      d="1"
      shift
      ;;
    --return-voxels)
      r="1"
      shift
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

python - "$f" "$m" "$n" "$d" "$r" <<'PY'
from pathlib import Path
import json
import sys
from fran.data.datasource import Datasource

f = Path(sys.argv[1]).expanduser().resolve()
m = sys.argv[2]
n = int(sys.argv[3])
d = int(sys.argv[4])
r = int(sys.argv[5])

ds = Datasource(folder=f, name=m)
out = ds.update_datasource(
    return_voxels=bool(r),
    num_processes=n,
    multiprocess=n > 1,
    dry_run=bool(d),
)
print(json.dumps(out, indent=2))
PY
