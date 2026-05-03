#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./git_all.sh [branch]
  ./git_all.sh --mode pull [branch]
  ./git_all.sh --mode reset [branch]
  ./git_all.sh --cold-storage /abs/path [--mode pull|reset] [branch]
EOF
}

MODE="reset"
BRANCH="main"
COLD_STORAGE_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --cold-storage)
      COLD_STORAGE_ARG="$2"
      shift 2
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      BRANCH="$1"
      shift
      ;;
  esac
done

if [[ -n "$COLD_STORAGE_ARG" ]]; then
  COLD_STORAGE="$COLD_STORAGE_ARG"
fi

: "${COLD_STORAGE:?COLD_STORAGE is not set}"
ROOT="$COLD_STORAGE/code"

if [[ ! -d "$ROOT" ]]; then
  echo "Directory not found: $ROOT"
  exit 1
fi

echo "Scanning git repos under: $ROOT"
echo "Mode: $MODE"
echo "Branch: $BRANCH"
echo "Skipping repo named: ITK"
echo

find "$ROOT" -type d -name ".git" -prune | while IFS= read -r gitdir; do
  repo="${gitdir%/.git}"

  if [[ "$(basename "$repo")" == "ITK" ]]; then
    echo "=== $repo ==="
    echo "Skipping: excluded repo"
    echo
    continue
  fi

  echo "=== $repo ==="

  if git -C "$repo" ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
    git -C "$repo" fetch origin "$BRANCH"
    if [[ "$MODE" == "pull" ]]; then
      git -C "$repo" checkout "$BRANCH"
      git -C "$repo" pull --ff-only origin "$BRANCH"
      echo "Pulled origin/$BRANCH"
    elif [[ "$MODE" == "reset" ]]; then
      git -C "$repo" reset --hard "origin/$BRANCH"
      git -C "$repo" clean -fd
      echo "Updated to origin/$BRANCH"
    else
      echo "Unknown mode: $MODE"
      exit 2
    fi
  else
    echo "Skipping: origin/$BRANCH not found"
  fi
  echo
done

echo "Done."
