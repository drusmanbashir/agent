#!/usr/bin/env bash
set -euo pipefail

CONF="${AGENT_SECRETS_FILE:-/s/agent_rw/conf/agent_repo/secrets.env}"
mkdir -p "$(dirname "$CONF")"
touch "$CONF"

update_key() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  grep -Ev "^${key}=" "$CONF" > "$tmp" || true
  printf '%s="%s"\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$CONF"
}

if [[ $# -ge 2 ]]; then
  BOT_TOKEN="$1"
  CHAT_ID="$2"
  SENDER="${3:-agent}"
  update_key "TELEGRAM_BOT_TOKEN" "$BOT_TOKEN"
  update_key "TELEGRAM_CHAT_ID" "$CHAT_ID"
  update_key "TELEGRAM_SENDER" "$SENDER"
  chmod 600 "$CONF"
  echo "Wrote $CONF"
else
  echo "Usage: $0 <BOT_TOKEN> <CHAT_ID> [SENDER]"
  echo "Config path: $CONF"
fi
