#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/home/palac/satnogs-pipeline/logs"
mkdir -p "$LOG_DIR"

{
  echo "==== post observation $(date -Is) ===="
  echo "args: $*"
  echo "--- env ---"
  env | sort
  echo
} >> "$LOG_DIR/post_observation.log"