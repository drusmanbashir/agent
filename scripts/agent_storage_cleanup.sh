#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/home/ub/code/agent"
# shellcheck source=/dev/null
source "${REPO_ROOT}/agent/hpc/cli/storage_roots.sh"
load_storage_roots

TMP_DAYS="${TMP_DAYS:-7}"
BACKUP_DAYS="${BACKUP_DAYS:-30}"
SCRATCH_ROOT="/s/agent_rw/.tmp"
BACKUP_ROOT="${AGENT_TMP_ROOT}/hpc_agent_backups"

prune_root() {
  local root="$1"
  local days="$2"
  [ -d "${root}" ] || return 0
  find "${root}" -mindepth 1 -maxdepth 1 -mtime "+${days}" -exec rm -rf {} +
}

mkdir -p "${AGENT_TMP_ROOT}" "${BACKUP_ROOT}"
find "${AGENT_TMP_ROOT}" -mindepth 1 -maxdepth 1 ! -name "$(basename "${BACKUP_ROOT}")" -mtime "+${TMP_DAYS}" -exec rm -rf {} +
prune_root "${BACKUP_ROOT}" "${BACKUP_DAYS}"
prune_root "${SCRATCH_ROOT}" "${TMP_DAYS}"
