#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/opt/satnogs-non-free/hooks/logs"
mkdir -p "$LOG_DIR"

{
  echo "==== post observation $(date -Is) ===="
  echo "args: $*"
  echo "--- env ---"
  env | sort | sed -E 's/(TOKEN|PASSWORD|SECRET|KEY)=.*/\1=<redacted>/'
  echo
  echo "--- iq dumps ---"
  find /tmp/.satnogs/data -maxdepth 1 -type f -name 'iq_cs16_*.raw' \
   -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' | sort | tail -5
} >> "$LOG_DIR/post_observation.log"
