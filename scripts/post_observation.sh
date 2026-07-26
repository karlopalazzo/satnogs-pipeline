#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/opt/satnogs-non-free/hooks/logs"
IQ_ARCHIVE="/opt/satnogs-non-free/iq-archive"
mkdir -p "$LOG_DIR" "$IQ_ARCHIVE"

{
  echo "==== post observation $(date -Is) ===="
  echo "args: $*"
  echo "--- env ---"
  env | sort | sed -E 's/(TOKEN|PASSWORD|SECRET|KEY)=.*/\1=<redacted>/'
  echo
  echo "--- iq dumps ---"
  find /tmp/.satnogs/data -maxdepth 1 -type f -name 'iq_cs16_*.raw' \
    -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' | sort | tail -5
  echo "--- archive copies ---"
  find /tmp/.satnogs/data -maxdepth 1 -type f -name 'iq_cs16_*.raw' -mmin -45 | while read -r iq_file; do
    cp -a "$iq_file" "$IQ_ARCHIVE/"
    echo "archived $(basename "$iq_file")"
  done
} >> "$LOG_DIR/post_observation.log"
