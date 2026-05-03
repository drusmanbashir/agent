#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/home/ub/mambaforge/envs/dl/bin/python"
cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
Usage:
  hpc_xfer.sh [--dry-run] download <dest_local>
  hpc_xfer.sh [--dry-run] download <src_remote> <dest_local>
  hpc_xfer.sh [--dry-run] upload <src_local>
  hpc_xfer.sh [--dry-run] upload <src_local> <dest_remote>

Notes:
  - Download one-arg mode uses default source on HPC.
  - Upload one-arg mode uses default destination on HPC.
  - Remote paths are normalized to user@host:/path using FRAN HPC config when available.
  - '$COLD_STORAGE@hpc' expands to the remote cold_storage_folder when FRAN config is present.

Env defaults:
  HPC_DEFAULT_DOWNLOAD_SRC  default: /s/agent_rw/
  HPC_DEFAULT_UPLOAD_DEST   default: \$COLD_STORAGE@hpc
  COLD_STORAGE              optional local cold-storage fallback for @hpc expansion
  FRAN_CONF                 used to read hpc.yaml, config.yaml, and config_hpc.yaml
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

yaml_get() {
  local file="$1"
  local key="$2"
  "${PYTHON_BIN}" - "$file" "$key" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
key = sys.argv[2]
if not path.exists():
    raise SystemExit(1)

try:
    import yaml  # type: ignore
except Exception:
    data = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        if line[:1].isspace() or ":" not in line:
            continue
        current_key, value = line.split(":", 1)
        current_key = current_key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        data[current_key] = value
else:
    loaded = yaml.safe_load(path.read_text()) or {}
    if not isinstance(loaded, dict):
        raise SystemExit(1)
    data = loaded

value = data.get(key)
if value is None:
    raise SystemExit(1)
print(value)
PY
}

default_login() {
  local login=""
  if login="$("${PYTHON_BIN}" -m tools.cli load_pwd --field login --format plain 2>/dev/null)"; then
    printf '%s\n' "$login"
    return 0
  fi
  if [[ -n "${HPC_LOGIN:-}" ]]; then
    printf '%s\n' "${HPC_LOGIN}"
    return 0
  fi
  if [[ -n "${HPC_HOST_ALIAS:-}" ]]; then
    printf '%s\n' "${HPC_HOST_ALIAS}"
    return 0
  fi
  die "could not resolve HPC login from tools.cli, \$HPC_LOGIN, or \$HPC_HOST_ALIAS"
}

config_path() {
  local name="$1"
  local conf_root="${FRAN_CONF:-}"
  [[ -n "$conf_root" ]] || return 1
  printf '%s/%s\n' "${conf_root%/}" "$name"
}

remote_cold_storage() {
  local path=""
  path="$(config_path config_hpc.yaml)" || return 1
  yaml_get "$path" cold_storage_folder
}

local_cold_storage() {
  if [[ -n "${COLD_STORAGE:-}" ]]; then
    printf '%s\n' "${COLD_STORAGE}"
    return 0
  fi
  local path=""
  path="$(config_path config.yaml)" || return 1
  yaml_get "$path" cold_storage_folder
}

resolve_remote_spec() {
  local raw="$1"
  local login="$2"
  local remote_cold="${3:-}"
  local local_cold="${4:-}"

  if [[ "$raw" == *:* ]]; then
    printf '%s\n' "$raw"
    return 0
  fi

  if [[ "$raw" == '$COLD_STORAGE@hpc' || "$raw" == '${COLD_STORAGE}@hpc' ]]; then
    if [[ -n "$remote_cold" ]]; then
      printf '%s:%s\n' "$login" "$remote_cold"
      return 0
    fi
    if [[ -n "$local_cold" ]]; then
      printf '%s:%s\n' "$login" "$local_cold"
      return 0
    fi
    die "cannot expand $raw without FRAN config or \$COLD_STORAGE"
    return 0
  fi

  if [[ "$raw" == *"@"* ]]; then
    local maybe_path="${raw%@*}"
    local maybe_host="${raw##*@}"

    if [[ "$maybe_host" == "hpc" ]]; then
      if [[ -n "$remote_cold" && "$maybe_path" == '$COLD_STORAGE' ]]; then
        printf '%s:%s\n' "$login" "$remote_cold"
        return 0
      fi
      if [[ -n "$remote_cold" && -n "$local_cold" && "$maybe_path" == "$local_cold" ]]; then
        printf '%s:%s\n' "$login" "$remote_cold"
        return 0
      fi
      if [[ -n "$remote_cold" && "$maybe_path" == '$COLD_STORAGE/'* ]]; then
        printf '%s:%s/%s\n' "$login" "$remote_cold" "${maybe_path#'$COLD_STORAGE/'}"
        return 0
      fi
      if [[ -n "$remote_cold" && -n "$local_cold" && "$maybe_path" == "$local_cold/"* ]]; then
        printf '%s:%s/%s\n' "$login" "$remote_cold" "${maybe_path#"$local_cold/"}"
        return 0
      fi
    fi

    if [[ "$maybe_path" == /* && -n "$maybe_host" ]]; then
      if [[ "$maybe_host" == "hpc" ]]; then
        printf '%s:%s\n' "$login" "$maybe_path"
      else
        printf '%s:%s\n' "$maybe_host" "$maybe_path"
      fi
      return 0
    fi
  fi

  if [[ "$raw" == /* ]]; then
    printf '%s:%s\n' "$login" "$raw"
    return 0
  fi

  die "cannot resolve remote path spec: $raw"
}

run_rsync() {
  local src="$1"
  local dest="$2"
  local dry_run="$3"
  local -a cmd=("${SCRIPT_DIR}/hpc_rsync.sh" "-avz" "--partial")
  if [[ "$dry_run" == "1" ]]; then
    cmd+=("--dry-run")
  fi
  cmd+=("$src" "$dest")
  echo "${cmd[*]}"
  "${cmd[@]}"
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 2; }

  local dry_run=0
  if [[ "${1:-}" == "--dry-run" ]]; then
    dry_run=1
    shift
  fi

  local action="$1"
  shift

  local login
  login="$(default_login)"
  local default_download_src="${HPC_DEFAULT_DOWNLOAD_SRC:-/s/agent_rw/}"
  local remote_cold=""
  local local_cold=""
  remote_cold="$(remote_cold_storage 2>/dev/null || true)"
  local_cold="$(local_cold_storage 2>/dev/null || true)"

  case "$action" in
    download)
      local src_remote
      local dest_local
      if [[ $# -eq 1 ]]; then
        src_remote="$(resolve_remote_spec "$default_download_src" "$login" "$remote_cold" "$local_cold")"
        dest_local="$1"
      elif [[ $# -eq 2 ]]; then
        src_remote="$(resolve_remote_spec "$1" "$login" "$remote_cold" "$local_cold")"
        dest_local="$2"
      else
        usage
        exit 2
      fi
      mkdir -p "$dest_local"
      run_rsync "$src_remote" "$dest_local" "$dry_run"
      ;;

    upload)
      local src_local
      local dest_remote
      local default_upload_raw="${HPC_DEFAULT_UPLOAD_DEST:-\$COLD_STORAGE@hpc}"
      local default_upload_dest
      default_upload_dest="$(resolve_remote_spec "$default_upload_raw" "$login" "$remote_cold" "$local_cold")"
      if [[ $# -eq 1 ]]; then
        src_local="$1"
        dest_remote="$default_upload_dest"
      elif [[ $# -eq 2 ]]; then
        src_local="$1"
        dest_remote="$(resolve_remote_spec "$2" "$login" "$remote_cold" "$local_cold")"
      else
        usage
        exit 2
      fi
      [[ -e "$src_local" ]] || die "local source does not exist: $src_local"
      run_rsync "$src_local" "$dest_remote" "$dry_run"
      ;;

    -h|--help|help)
      usage
      ;;

    *)
      usage
      die "unknown action: $action"
      ;;
  esac
}

main "$@"
