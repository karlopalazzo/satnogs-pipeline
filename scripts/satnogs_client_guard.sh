#!/usr/bin/env bash
# Restart SatNOGS client if extra/stuck processes block GNU Radio ZMQ (empty waterfall).
set -euo pipefail

CONTAINER="satnogs_satnogs-client"
LOG_TAG="satnogs_client_guard"

if ! sudo docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "$LOG_TAG: container $CONTAINER not found"
  exit 0
fi

mapfile -t lines < <(
  sudo docker exec "$CONTAINER" sh -c "ps aux 2>/dev/null | grep satnogs-client | grep -v grep || true"
)

count="${#lines[@]}"
bad=0
for line in "${lines[@]}"; do
  if [[ "$line" == *"--help"* ]] || [[ "$line" == *"satnogs-client --"* ]]; then
    bad=1
  fi
done

if [[ "$count" -eq 1 && "$bad" -eq 0 ]]; then
  exit 0
fi

echo "$LOG_TAG: unexpected satnogs-client processes (count=$count), restarting $CONTAINER"
printf '%s\n' "${lines[@]}"
sudo docker restart "$CONTAINER" >/dev/null
echo "$LOG_TAG: restart finished"
