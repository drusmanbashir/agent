#!/bin/bash
#SBATCH -J datasource_init
#SBATCH -D /data/EECS-LITQ/fran_storage/logs
#SBATCH -n 16
#SBATCH -t 3:00:00
#SBATCH --mem-per-cpu=8G
#SBATCH -o /data/EECS-LITQ/fran_storage/logs/%x-%j.out
#SBATCH -e /data/EECS-LITQ/fran_storage/logs/%x-%j.err


module load miniforge
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl

folder="${FOLDER:-}"
mnemonic="${MNEMONIC:-}"
num_processes="${NUM_PROCESSES:-1}"
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
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

[[ ${#positionals[@]} -ge 1 ]] && folder="${positionals[0]}"
[[ ${#positionals[@]} -ge 2 ]] && mnemonic="${positionals[1]}"

if [[ -z "${folder}" || -z "${mnemonic}" ]]; then
  echo "Usage: $0 <folder> <mnemonic> [-n|--num-processes N]" >&2
  echo "       FOLDER=<folder> MNEMONIC=<mnemonic> NUM_PROCESSES=N $0" >&2
  exit 2
fi

python /data/EECS-LITQ/fran_storage/code/fran/fran/run/datasource_init.py \
  "$folder" \
  "$mnemonic" \
  -n "$num_processes"
