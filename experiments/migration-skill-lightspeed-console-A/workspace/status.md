# Migration Status

## Project Type
- IS_CONSOLE_PLUGIN=true
- Indicators: `@openshift-console/dynamic-plugin-sdk` in dependencies, `console-extensions.json` exists
- Plugin name: lightspeed-console-plugin

## Build System
- Build: `npm run build`
- Lint: `npm run lint-fix`
- E2E Tests: `npm run test-headless` (Cypress)
- Dev server: `npm run start` (port 9001) + `start-console.sh` (port 9000)

## Visual Baseline

**SKIPPED** — OpenShift Console bridge container (`quay.io/openshift/origin-console`) crashes under QEMU x86_64 emulation on ARM Mac (SIGSEGV in Go runtime `netpoll_epoll.go`). Tested images 4.12, 4.15, 4.18 with both podman and docker — all crash. The plugin UI only renders inside the console shell, so visual baseline screenshots cannot be captured without a working bridge. Visual testing will be done during cluster validation phase if possible.

## Migration: PatternFly 5 → PatternFly 6
