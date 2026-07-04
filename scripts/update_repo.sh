#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/palac/satnogs-pipeline"
cd "$ROOT"

echo "[$(date -Is)] update_repo: start"

# Avoid auto-updating over local tracked modifications.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[$(date -Is)] update_repo: skipped (tracked local changes present)"
  exit 1
fi

# Refresh remote refs first.
git fetch --prune origin

# Handle branch state safely (no implicit merge commits).
LOCAL="$(git rev-parse @)"
UPSTREAM="$(git rev-parse @{u})"
BASE="$(git merge-base @ @{u})"

if [[ "$LOCAL" == "$UPSTREAM" ]]; then
  echo "[$(date -Is)] update_repo: already up to date"
  exit 0
fi

if [[ "$LOCAL" == "$BASE" ]]; then
  echo "[$(date -Is)] update_repo: fast-forwarding"
  git pull --ff-only
  echo "[$(date -Is)] update_repo: updated successfully"
  exit 0
fi

if [[ "$UPSTREAM" == "$BASE" ]]; then
  echo "[$(date -Is)] update_repo: local branch ahead of upstream, no pull"
  exit 0
fi

echo "[$(date -Is)] update_repo: skipped (branch diverged from upstream)"
exit 1
