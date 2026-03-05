#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OS="$(uname -s)"

SERVICE_NAME="agent-hub"
PLIST_LABEL="com.drusman.agent-hub"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

PYTHON_BIN="${AGENT_HUB_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$HOME/mambaforge/envs/dl/bin/python3" ]]; then
    PYTHON_BIN="$HOME/mambaforge/envs/dl/bin/python3"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

usage() {
  cat <<EOF
Usage: $0 <command>

Commands:
  update          git pull --ff-only in repo
  install         install service for current OS and start it
  start           start service
  stop            stop service
  restart         restart service
  status          show service status
  update-restart  update from github, then restart service

Optional env:
  AGENT_HUB_PYTHON=/path/to/python3
EOF
}

update_repo() {
  git -C "$REPO_ROOT" pull --ff-only
}

linux_install() {
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Agent Hub local web portal
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO_ROOT
ExecStart=$PYTHON_BIN $REPO_ROOT/agent_hub.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE_NAME.service"
}

linux_start() { systemctl --user start "$SERVICE_NAME.service"; }
linux_stop() { systemctl --user stop "$SERVICE_NAME.service"; }
linux_restart() { systemctl --user restart "$SERVICE_NAME.service"; }
linux_status() { systemctl --user --no-pager --full status "$SERVICE_NAME.service"; }

mac_install() {
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$REPO_ROOT/agent_hub.py</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/agent-hub.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/agent-hub.err.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  launchctl enable "gui/$(id -u)/$PLIST_LABEL"
  launchctl kickstart -k "gui/$(id -u)/$PLIST_LABEL"
}

mac_start() { launchctl kickstart -k "gui/$(id -u)/$PLIST_LABEL"; }
mac_stop() { launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true; }
mac_restart() { mac_stop; launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"; launchctl kickstart -k "gui/$(id -u)/$PLIST_LABEL"; }
mac_status() { launchctl print "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || echo "Service not loaded: $PLIST_LABEL"; }

run_for_os() {
  local cmd="$1"
  case "$OS" in
    Linux)
      "linux_$cmd"
      ;;
    Darwin)
      "mac_$cmd"
      ;;
    *)
      echo "Unsupported OS: $OS" >&2
      exit 1
      ;;
  esac
}

case "${1:-}" in
  update)
    update_repo
    ;;
  install)
    run_for_os install
    ;;
  start)
    run_for_os start
    ;;
  stop)
    run_for_os stop
    ;;
  restart)
    run_for_os restart
    ;;
  status)
    run_for_os status
    ;;
  update-restart)
    update_repo
    run_for_os restart
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command: $1" >&2
    usage
    exit 1
    ;;
esac
