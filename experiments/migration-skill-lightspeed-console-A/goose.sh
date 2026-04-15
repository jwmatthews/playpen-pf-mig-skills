#!/bin/bash
set -euo pipefail

LOGFILE="${LOGFILE:-migration-$(date +%Y%m%d-%H%M%S).log}"

echo "Starting migration at $(date)" | tee "$LOGFILE"
echo "Log file: $LOGFILE" | tee -a "$LOGFILE"
echo "---" | tee -a "$LOGFILE"

require_on_path() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Error: ${name} not found on PATH (install it or adjust PATH)." | tee -a "$LOGFILE" >&2
    exit 1
  fi
}

require_on_path frontend-analyzer-provider
require_on_path kantra
require_on_path podman

if ! podman info >/dev/null 2>&1; then
  echo "Error: podman is not functional (daemon/machine unreachable). On macOS try: podman machine start" | tee -a "$LOGFILE" >&2
  exit 1
fi

time goose run --recipe ../../goose/recipes/migration.yaml \
  --params source_tech="PatternFly 5" \
  --params target_tech="PatternFly 6" \
  --params input_path="./lightspeed-console" \
  --params workspace_dir="./workspace" \
  --params rules="./semver-generated-rules-pf5-to-pf6" 2>&1 | tee -a "$LOGFILE"

EXIT_CODE=${PIPESTATUS[0]}
echo "---" | tee -a "$LOGFILE"
echo "Finished at $(date) with exit code: $EXIT_CODE" | tee -a "$LOGFILE"
exit $EXIT_CODE
