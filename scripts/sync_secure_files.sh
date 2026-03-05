#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ub/code/agent"
DEFAULT_MANIFEST="/s/agent_rw/conf/agent_repo/secure_files.manifest.tsv"
FALLBACK_MANIFEST="$ROOT/config/secure_files.manifest.tsv.example"
MANIFEST="${AGENT_SECURE_FILES_MANIFEST:-$DEFAULT_MANIFEST}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: sync_secure_files.sh [--dry-run] [--manifest PATH]

Synchronize sensitive repo-local files from secure external paths.
Manifest format (tab-separated, no header required):
  local_path <TAB> secure_source_path <TAB> mode
Where mode is:
  copy  -> copy source file into local_path
  link  -> create symlink local_path -> secure_source_path
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --manifest)
      MANIFEST="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! -f "$MANIFEST" ]]; then
  if [[ "$MANIFEST" == "$DEFAULT_MANIFEST" && -f "$FALLBACK_MANIFEST" ]]; then
    MANIFEST="$FALLBACK_MANIFEST"
  else
    echo "Manifest not found: $MANIFEST" >&2
    exit 1
  fi
fi

echo "Using manifest: $MANIFEST"

apply_copy() {
  local src="$1"
  local dst="$2"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] copy $src -> $dst"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  cp -f "$src" "$dst"
  chmod 600 "$dst" || true
  echo "copied $src -> $dst"
}

apply_link() {
  local src="$1"
  local dst="$2"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] link $dst -> $src"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  echo "linked $dst -> $src"
}

while IFS=$'\t' read -r local_path secure_path mode _; do
  [[ -z "${local_path// }" ]] && continue
  [[ "${local_path:0:1}" == "#" ]] && continue
  if [[ -z "${secure_path:-}" || -z "${mode:-}" ]]; then
    echo "Skipping malformed line: $local_path" >&2
    continue
  fi

  local_abs="$ROOT/$local_path"
  if [[ ! -e "$secure_path" ]]; then
    echo "Missing secure source, skipped: $secure_path"
    continue
  fi

  case "$mode" in
    copy) apply_copy "$secure_path" "$local_abs" ;;
    link) apply_link "$secure_path" "$local_abs" ;;
    *)
      echo "Unsupported mode '$mode' for $local_path" >&2
      ;;
  esac
done < "$MANIFEST"
