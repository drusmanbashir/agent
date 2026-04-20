#!/bin/bash
#SBATCH -J datasource_update
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 16
#SBATCH -t 3:00:00
#SBATCH --mem-per-cpu=8G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err

set -euo pipefail

module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl

folder="${FOLDER:-}"
mnemonic="${MNEMONIC:-}"
num_processes="${NUM_PROCESSES:-1}"
dry_run="${DRY_RUN:-0}"
return_voxels="${RETURN_VOXELS:-1}"
positionals=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--mnemonic)
      mnemonic="$2"
      shift 2
      ;;
    -n|--num-processes)
      num_processes="$2"
      shift 2
      ;;
    --dry-run)
      dry_run="1"
      shift
      ;;
    --return-voxels)
      return_voxels="1"
      shift
      ;;
    --no-return-voxels)
      return_voxels="0"
      shift
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

[[ ${#positionals[@]} -ge 1 ]] && folder="${positionals[0]}"
[[ ${#positionals[@]} -ge 2 ]] && mnemonic="${positionals[1]}"

if [[ -z "${folder}" || -z "${mnemonic}" ]]; then
  echo "Usage: $0 <folder> <mnemonic> [-n|--num-processes N] [--dry-run] [--no-return-voxels]" >&2
  echo "       FOLDER=<folder> MNEMONIC=<mnemonic> NUM_PROCESSES=N DRY_RUN=0|1 RETURN_VOXELS=0|1 $0" >&2
  exit 2
fi

py_script="$(mktemp "${TMPDIR:-/tmp}/datasource_update.XXXXXX.py")"
trap 'rm -f "$py_script"' EXIT

cat > "$py_script" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from fran.data.datasource import Datasource


folder = Path(sys.argv[1]).expanduser().resolve()
mnemonic = sys.argv[2]
num_processes = int(sys.argv[3])
dry_run = sys.argv[4] in {"1", "true", "True", "yes", "YES"}
return_voxels = sys.argv[5] in {"1", "true", "True", "yes", "YES"}

if num_processes < 1:
    raise ValueError("--num-processes must be >= 1")

ds = Datasource(folder=folder, name=mnemonic)
summary = ds.update_datasource(
    return_voxels=return_voxels,
    num_processes=num_processes,
    multiprocess=num_processes > 1,
    dry_run=dry_run,
)
print(json.dumps(summary, indent=2))
PY

python "$py_script" "$folder" "$mnemonic" "$num_processes" "$dry_run" "$return_voxels"
