#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <command...>" >&2
  exit 1
fi

CMD=("$@")
START_TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

/home/ub/code/agent/scripts/telegram_notify.sh "Started: ${CMD[*]} at ${START_TS}"

set +e
"${CMD[@]}"
STATUS=$?
set -e

END_TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
if [[ $STATUS -eq 0 ]]; then
  /home/ub/code/agent/scripts/telegram_notify.sh "Finished OK: ${CMD[*]} at ${END_TS}"
else
  /home/ub/code/agent/scripts/telegram_notify.sh "Failed (exit ${STATUS}): ${CMD[*]} at ${END_TS}"
fi

printf '\a'
exit $STATUS
