#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"
DEFAULT_RBD_JSON_REL="predictions/totalseg_localiser/train"

cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
Usage:
  rbd_json_upload.sh [--dry-run] [src_local] [dest_remote]

Behavior:
  - Uploads JSON files only.
  - Missing-only: existing remote JSONs are preserved via --ignore-existing.
  - Default source resolves to <local cold storage>/predictions/totalseg_localiser/train.
  - Default destination resolves to the mapped HPC path for the chosen source.

Examples:
  rbd_json_upload.sh
  rbd_json_upload.sh --dry-run
  rbd_json_upload.sh /s/fran_storage/predictions/totalseg_localiser/train
  rbd_json_upload.sh /s/fran_storage/predictions/totalseg_localiser/train mpx588@login.hpc.qmul.ac.uk:/data/EECS-LITQ/fran_storage/predictions/totalseg_localiser/train
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

print_cmd() {
  printf 'CMD'
  for arg in "$@"; do
    printf ' %q' "$arg"
  done
  printf '\n'
}

run_cmd() {
  print_cmd "$@"
  if [[ "${DRY_RUN}" == "1" ]]; then
    return 0
  fi
  "$@"
}

yaml_get() {
  local file="$1"
  local key="$2"
  "${PYTHON_BIN}" - "$file" "$key" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1]).expanduser()
key = sys.argv[2]
data = yaml.safe_load(path.read_text())
print(data[key])
PY
}

config_path() {
  local name="$1"
  printf '%s/%s\n' "${FRAN_CONF%/}" "$name"
}

local_cold_storage() {
  if [[ -n "${COLD_STORAGE:-}" ]]; then
    printf '%s\n' "${COLD_STORAGE}"
    return 0
  fi
  yaml_get "$(config_path config.yaml)" cold_storage_folder
}

resolve_remote_spec() {
  "${PYTHON_BIN}" -m tools.cli resolve_remote_spec "$1"
}

remote_quote() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import shlex
import sys

print(shlex.quote(sys.argv[1]))
PY
}

main() {
  DRY_RUN=0
  if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
  fi

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
    usage
    exit 0
  fi

  if [[ $# -gt 2 ]]; then
    usage
    exit 2
  fi

  local cold_storage
  cold_storage="$(local_cold_storage)"

  local src_local="${1:-${cold_storage%/}/${DEFAULT_RBD_JSON_REL}}"
  local dest_remote="${2:-$(resolve_remote_spec "${src_local}")}"

  [[ -d "${src_local}" ]] || die "local source directory does not exist: ${src_local}"

  local remote_login="${dest_remote%%:*}"
  local remote_path="${dest_remote#*:}"
  [[ -n "${remote_login}" && -n "${remote_path}" && "${remote_path}" == /* ]] || die "invalid remote destination: ${dest_remote}"

  local quoted_remote_path
  quoted_remote_path="$(remote_quote "${remote_path}")"

  run_cmd "${SCRIPT_DIR}/hpc_ssh.sh" --login "${remote_login}" "mkdir -p ${quoted_remote_path}"
  run_cmd "${SCRIPT_DIR}/hpc_rsync.sh" \
    -avz \
    --partial \
    --ignore-existing \
    --prune-empty-dirs \
    --include='*/' \
    --include='*.json' \
    --exclude='*' \
    "${src_local%/}/" \
    "${dest_remote%/}/"
}

main "$@"
