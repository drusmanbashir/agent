#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./git_all.sh [branch]
# Example:
#   ./git_all.sh main
BRANCH="${1:-main}"

: "${COLD_STORAGE:?COLD_STORAGE is not set}"
ROOT="$COLD_STORAGE/code"

if [[ ! -d "$ROOT" ]]; then
  echo "Directory not found: $ROOT"
  exit 1
fi

echo "Scanning git repos under: $ROOT"
echo "Hard resetting each repo to origin/$BRANCH"
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
    git -C "$repo" fetch origin
    git -C "$repo" reset --hard "origin/$BRANCH"
    git -C "$repo" clean -fd
    echo "Updated to origin/$BRANCH"
  else
    echo "Skipping: origin/$BRANCH not found"
  fi
  echo
done

echo "Done."
