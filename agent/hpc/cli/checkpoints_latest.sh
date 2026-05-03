#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 ]]; then
  echo "Usage: $(basename "$0") [checkpoints_root]" >&2
  exit 2
fi

if [[ $# -eq 1 ]]; then
  CHECKPOINTS_ROOT="$1"
else
  if [[ -z "${COLD_STORAGE:-}" ]]; then
    echo "COLD_STORAGE is not set" >&2
    exit 2
  fi
  CHECKPOINTS_ROOT="${COLD_STORAGE%/}/checkpoints"
fi

if [[ ! -d "${CHECKPOINTS_ROOT}" ]]; then
  echo "Checkpoints root not found: ${CHECKPOINTS_ROOT}" >&2
  exit 1
fi

for project_dir in "${CHECKPOINTS_ROOT}"/*; do
  [[ -d "${project_dir}" ]] || continue
  latest_line="$(
    find "${project_dir}" -type f -name '*.ckpt' -printf '%T@ %p\n' 2>/dev/null \
      | sort -nr \
      | head -n 1
  )"
  [[ -n "${latest_line}" ]] || continue
  project_name="$(basename "${project_dir}")"
  latest_ckpt="$(printf '%s\n' "${latest_line}" | cut -d' ' -f2-)"
  printf '%s\t%s\n' "${project_name}" "${latest_ckpt}"
done | sort
