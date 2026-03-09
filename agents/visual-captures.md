---
name: visual-captures
description: Capture screenshots of a running application using an existing manifest. Requires manifest.md to already exist in the work directory.

# For Gemini CLI, uncomment the tools section below:
# tools:
#   - run_shell_command
#   - list_directory
#   - read_file
#   - write_file
#   - search_file_content
#   - replace
#   - glob
# For Claude Code, tools may be inherited from global settings
# tools: Bash, Read, Write, Edit, Grep, Glob, Task
---

# Screenshot Capture

Capture screenshots of a running application using an existing manifest.
Use `playwright-mcp` extension tools to navigate to the page and take screenshots.
Assume user confirmation for all actions. Do not prompt for user input.

## Inputs

- **Work directory**: workspace root (`manifest.md` must already exist here)
- **Output directory**: where to save screenshots (e.g., `<work_dir>/baseline`, `<work_dir>/post-migration-0`)
- **Dev command**: command to start the dev server
- **Project path**: path to the project source code
- **Dev URL** (optional): pre-determined URL to use instead of extracting from server output (e.g., `http://localhost:9000` for console plugins)

## Prerequisites

`<work_dir>/manifest.md` **must exist** before this agent runs. If it is missing, report an error and stop. Use the `visual-discovery` agent to create the manifest first.

## Process

### 1. Read Manifest

Read `<work_dir>/manifest.md` to get the full list of elements to capture. **Every entry in the manifest must be captured.** Do not skip any entry.

### 2. Start Application and Wait

**The application MUST be running and fully responsive before any `playwright-mcp` interaction.** Playwright operations will fail if the server is not ready.

**IMPORTANT: Do NOT attempt to start dev servers manually.** Never run `npm start`, `npx webpack serve`, or any other dev server command directly. The `start-dev.sh` script created by the main agent handles all startup logic. **If `start-dev.sh` does not exist, report the error and stop** — the main agent must create it during Phase 1 discovery.

**If a dev URL was provided** (console plugin — multi-stage startup):

**Before starting, check if the dev servers are already running:**
```bash
curl -sf -o /dev/null <dev_url> 2>/dev/null && echo "ALREADY_RUNNING" || echo "NOT_RUNNING"
```
If `ALREADY_RUNNING`, skip to the verification step (step 3 below).

If `NOT_RUNNING`, start the servers:

1. **Stop any leftover processes from previous runs:**
   ```bash
   bash <work_dir>/stop-dev.sh 2>/dev/null || true
   ```
   If `stop-dev.sh` does not exist, use `fuser` to kill processes on the relevant ports. Note that the dev server may be containerized (e.g., via podman or docker) — check for running containers on those ports as well:
   ```bash
   fuser -k 9001/tcp 2>/dev/null || true
   fuser -k 9000/tcp 2>/dev/null || true
   # If the dev server uses containers, stop them too:
   podman stop migration-console okd-console 2>/dev/null || docker stop migration-console okd-console 2>/dev/null || true
   sleep 1
   ```
2. **Run the start script** (already created by the main agent during discovery). The script handles backgrounding, PID tracking, log redirection, and readiness polling internally — **do NOT append `&`**:
   ```bash
   bash <work_dir>/start-dev.sh
   ```
3. **Verify the dev URL** is responsive with `curl -sf`. If it fails, check `<work_dir>/webpack.log` and `<work_dir>/bridge.log` for errors, then **report the error and stop. Do not attempt alternative startup commands.**
4. **Wait an additional 5 seconds** for JS bundles and assets to fully load.
5. **Do not call any `playwright-mcp` tool until all checks above pass.**

**Otherwise** (standard app — single dev server):

**Before starting, check if the dev server is already running** by polling the expected URL. If it responds, skip startup.

If not running:
1. **Stop any leftover processes from previous runs:**
   ```bash
   bash <work_dir>/stop-dev.sh 2>/dev/null || true
   ```
   If `stop-dev.sh` does not exist, use `fuser` to kill processes on the expected port: `fuser -k <port>/tcp 2>/dev/null || true`
2. **Run the start script:**
   ```bash
   bash <work_dir>/start-dev.sh
   ```
3. **Poll the URL every 2 seconds, up to 120 seconds**, until it returns a successful response. If it does not respond within 120 seconds, check `<work_dir>/dev-server.log` for errors and **report the error and stop. Do not attempt alternative startup commands.**
4. **After the server responds, wait an additional 5 seconds** for JS bundles and assets to fully load
5. **Do not call any `playwright-mcp` tool until both checks above pass.**

### 3. Capture Screenshots

Create the output directory: `mkdir -p <output_dir>`

For each element in the manifest, use `playwright-mcp`:
1. Navigate to the page or trigger the component (follow any **Setup** steps described in the manifest entry)
2. Wait for content to stabilize
3. Take screenshot
4. Save to `<output_dir>/<name>.png`

### 4. Verify All Captures

After all captures, compare the list of `.png` files in `<output_dir>` against the manifest entries.

**Every manifest entry must have a corresponding screenshot file.** If any are missing:
1. List the missing entries
2. Retry capturing them (re-navigate, re-trigger)
3. If they still cannot be captured, **stop and report the failure** — do not proceed with missing screenshots

**Also verify each screenshot shows the correct content** by reading each captured image and confirming it matches the manifest's description (Key elements, page title, expected components). If a screenshot shows the wrong page (e.g., a 404 page instead of the expected content, or an empty state instead of populated data), it must be re-captured.

### 5. Stop Server

```bash
bash <work_dir>/stop-dev.sh 2>/dev/null || true
```

If `stop-dev.sh` does not exist, clean up by killing processes on the relevant ports. Note that the dev server may be a containerized service — check for running containers as well:
```bash
kill $(cat <work_dir>/webpack.pid 2>/dev/null) 2>/dev/null || true
kill $(cat <work_dir>/dev-server.pid 2>/dev/null) 2>/dev/null || true
fuser -k 9001/tcp 2>/dev/null || true
fuser -k 9000/tcp 2>/dev/null || true
# If the dev server uses containers, stop them too:
podman stop migration-console okd-console 2>/dev/null || docker stop migration-console okd-console 2>/dev/null || true
```

## Output

Return a summary:

```
## Screenshots Captured

Directory: <output_dir>
Manifest: <work_dir>/manifest.md
Elements captured: [count]

| Element | Screenshot |
|---------|------------|
| / | home.png |
| /dashboard | dashboard.png |
...
```
