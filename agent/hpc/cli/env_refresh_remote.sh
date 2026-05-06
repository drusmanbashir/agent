#!/usr/bin/env bash
set -euo pipefail

mode="$1"
shift
remote_python="${1:-${HPC_ENV_REFRESH_REMOTE_PYTHON:-/data/home/mpx588/.conda/envs/dl/bin/python}}"
shift || true

case "${mode}" in
  query)
    "${remote_python}" - "$@" <<'PY'
from importlib import metadata
import sys

installed = {}
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if name:
        installed[name.lower()] = dist.version

for package in sys.argv[1:]:
    print(f"{package}\t{installed.get(package.lower(), '-')}")
PY
    ;;
  install)
    "${remote_python}" -m pip install --upgrade "$@"
    ;;
  *)
    echo "unknown mode: ${mode}" >&2
    exit 2
    ;;
esac
