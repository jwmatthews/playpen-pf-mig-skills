#!/bin/bash
WORK_DIR="./workspace"
PROJECT_PATH="./lightspeed-console"

# Cleanup: kill leftover processes from previous runs (macOS-compatible)
lsof -ti:9001 | xargs kill -9 2>/dev/null || true
lsof -ti:9000 | xargs kill -9 2>/dev/null || true
podman stop migration-console okd-console 2>/dev/null || true
podman rm -f migration-console okd-console 2>/dev/null || true
sleep 1

# 1. Start webpack dev server in background
cd "$PROJECT_PATH"
nohup npx ts-node -O '{"module":"commonjs"}' node_modules/.bin/webpack serve > "$OLDPWD/$WORK_DIR/webpack.log" 2>&1 &
echo $! > "$OLDPWD/$WORK_DIR/webpack.pid"
cd "$OLDPWD"

# 2. Poll until webpack dev server is ready on port 9001 (up to 120s)
for i in $(seq 1 60); do
  curl -sf -o /dev/null http://localhost:9001 2>/dev/null; rc=$?
  [ $rc -eq 0 ] || [ $rc -eq 22 ] && break
  sleep 2
done
echo "Webpack dev server ready on port 9001"

# 3. Start console bridge in background (blocking — podman run without -d)
# On macOS ARM: use --platform linux/amd64 and port mapping (no --network=host)
# Use host.containers.internal to reach host services from inside the container
nohup podman run --platform linux/amd64 --rm --name=migration-console \
  -p 9000:9000 \
  -e BRIDGE_USER_AUTH="disabled" \
  -e BRIDGE_K8S_MODE="off-cluster" \
  -e BRIDGE_K8S_AUTH="bearer-token" \
  -e BRIDGE_K8S_MODE_OFF_CLUSTER_SKIP_VERIFY_TLS=true \
  -e BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT="https://host.containers.internal:64231" \
  -e BRIDGE_K8S_AUTH_BEARER_TOKEN="eyJhbGciOiJSUzI1NiIsImtpZCI6Ik9rdFk5cFVBTlYwU0VuLV9VVGd2LVZmVUJJZmxpYTN2Z0R0UlNvTTZIWGsifQ.eyJpc3MiOiJrdWJlcm5ldGVzL3NlcnZpY2VhY2NvdW50Iiwia3ViZXJuZXRlcy5pby9zZXJ2aWNlYWNjb3VudC9uYW1lc3BhY2UiOiJvcGVuc2hpZnQtY29uc29sZSIsImt1YmVybmV0ZXMuaW8vc2VydmljZWFjY291bnQvc2VjcmV0Lm5hbWUiOiJvcGVuc2hpZnQtY29uc29sZS10b2tlbiIsImt1YmVybmV0ZXMuaW8vc2VydmljZWFjY291bnQvc2VydmljZS1hY2NvdW50Lm5hbWUiOiJvcGVuc2hpZnQtY29uc29sZSIsImt1YmVybmV0ZXMuaW8vc2VydmljZWFjY291bnQvc2VydmljZS1hY2NvdW50LnVpZCI6ImNjMWEzZTkxLTE4OTAtNDY3MS1iMjIwLTYxNjU2NjllYWFiZCIsInN1YiI6InN5c3RlbTpzZXJ2aWNlYWNjb3VudDpvcGVuc2hpZnQtY29uc29sZTpvcGVuc2hpZnQtY29uc29sZSJ9.lCFeZq0RbphbxqSIW2toZWQLK_vJRIdnYCRoiuV9--DlsuWXT009XOWvbTPR-ceW-IyeS7QAphMtk_y1MoF69EINwbyUS-EzYvCkPwqkBDMxgd8nfHOlsoGoDuk-2oGTcaKScM6jSnrH0pG8XrpsEpT9Q9mJb4Gb9F3wOFiBMjJah2YSFiy_OI7G4MvrIYaxspf7V20rQjNMCWC3Yks0NuKBBILiQN2WqkwNGLSyNYnsdpXRcJ6Q5wVl3r_iy7CVFMNIWYYiYywXmNzWfBA2eeH412_N9NvTJHWvKjF_QDjfeh0xCase0zg8H1NXfeaxkGzyjRLBJU_2xpao6q1eQw" \
  -e BRIDGE_USER_SETTINGS_LOCATION="localstorage" \
  -e BRIDGE_PLUGINS="lightspeed-console-plugin=http://host.containers.internal:9001" \
  -e BRIDGE_LISTEN="http://0.0.0.0:9000" \
  quay.io/openshift/origin-console:4.18 > "$WORK_DIR/bridge.log" 2>&1 &
echo $! > "$WORK_DIR/bridge.pid"

# 4. Poll until console bridge is ready on port 9000 (up to 180s)
for i in $(seq 1 90); do
  curl -sf -o /dev/null http://localhost:9000 2>/dev/null && break
  sleep 2
done
echo "Dev servers ready"
