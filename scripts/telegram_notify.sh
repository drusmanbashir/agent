#!/usr/bin/env bash
set -euo pipefail

DEFAULT_SECRETS_FILE="/s/agent_rw/conf/agent_repo/secrets.env"

resolve_conf() {
  if [[ -n "${TELEGRAM_CONF_PATH:-}" && -f "${TELEGRAM_CONF_PATH}" ]]; then
    echo "$TELEGRAM_CONF_PATH"
    return 0
  fi

  if [[ -n "${AGENT_SECRETS_FILE:-}" && -f "${AGENT_SECRETS_FILE}" ]]; then
    echo "$AGENT_SECRETS_FILE"
    return 0
  fi

  if [[ -f "$DEFAULT_SECRETS_FILE" ]]; then
    echo "$DEFAULT_SECRETS_FILE"
    return 0
  fi

  return 1
}

CONF_PATH="$(resolve_conf || true)"
if [[ -z "$CONF_PATH" ]]; then
  echo "No usable Telegram config found. Checked:"
  echo "  - TELEGRAM_CONF_PATH (if set)"
  echo "  - AGENT_SECRETS_FILE (if set)"
  echo "  - $DEFAULT_SECRETS_FILE"
  exit 1
fi

# shellcheck disable=SC1090
source "$CONF_PATH"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in $CONF_PATH" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 \"message\"" >&2
  exit 1
fi

MESSAGE="$*"
SENDER="${TELEGRAM_SENDER:-agent}"
HOST="$(hostname)"
TEXT="[$SENDER@$HOST] $MESSAGE"

curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${TEXT}" >/dev/null

echo "Telegram notification sent"
