#!/usr/bin/env bash
set -e

# Usage: ./git-hard-reset.sh [branch]
BRANCH="${1:-main}"

# Ensure we are inside a git repo
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository."
    exit 1
fi

git fetch origin
git reset --hard "origin/$BRANCH"
git clean -fd

echo "Repository reset to origin/$BRANCH"

