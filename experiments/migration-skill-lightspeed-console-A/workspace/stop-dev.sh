#!/bin/bash
WORK_DIR="./workspace"
kill $(cat "$WORK_DIR/webpack.pid" 2>/dev/null) 2>/dev/null || true
kill $(cat "$WORK_DIR/bridge.pid" 2>/dev/null) 2>/dev/null || true
podman stop migration-console okd-console 2>/dev/null || docker stop migration-console okd-console 2>/dev/null || true
# Kill any processes on ports 9001 and 9000 (macOS-compatible)
lsof -ti:9001 | xargs kill -9 2>/dev/null || true
lsof -ti:9000 | xargs kill -9 2>/dev/null || true
rm -f "$WORK_DIR/webpack.pid" "$WORK_DIR/bridge.pid"
echo "Dev servers stopped"
