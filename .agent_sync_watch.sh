#!/usr/bin/env bash
set -u
REPO=/home/ub/code/agent
LOG="$REPO/.agent_sync.log"
STATE="$REPO/.agent_sync.state"
COPILOT="$REPO/copilot.txt"
SCHEMA="$REPO/schema.txt"
HOMEFALLBACK="$HOME/.agent_sync_state"
mkdir -p "$HOMEFALLBACK"
last_hash=""
last_mtime=""
if [ -f "$STATE" ]; then
  . "$STATE"
fi
while true; do
  {
    printf "\n=== %s ===\n" "$(date -Is)"
    git -C "$REPO" pull --ff-only
    if [ -f "$COPILOT" ]; then
      hash_now="$(sha256sum "$COPILOT" | awk '{print $1}')"
      mtime_now="$(stat -c %Y "$COPILOT")"
      echo "copilot.txt present hash=$hash_now mtime=$mtime_now"
      if [ "$hash_now" != "${last_hash:-}" ]; then
        echo "copilot.txt changed"
        sed -n '1,200p' "$COPILOT"
        if [ -f "$SCHEMA" ]; then
          last_n=$(find "$REPO" -maxdepth 1 -type f -name 'schema-*.txt' | sed 's#.*/schema-##; s#\.txt##' | sort -n | tail -1)
          if [ -n "$last_n" ]; then
            next_n=$((last_n + 1))
          else
            next_n=1
          fi
          cp "$SCHEMA" "$REPO/schema-$next_n.txt"
          echo "snapshotted schema.txt -> schema-$next_n.txt"
        fi
        last_hash="$hash_now"
        last_mtime="$mtime_now"
      else
        echo "copilot.txt unchanged"
      fi
    else
      echo "copilot.txt missing"
    fi
    printf 'last_hash=%q\nlast_mtime=%q\n' "$last_hash" "$last_mtime" > "$STATE"
  } >> "$LOG" 2>&1
  sleep 300
done
