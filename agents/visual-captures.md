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

**If a dev URL was provided** (console plugin — multi-stage startup):

The dev command is a multi-stage script that starts two servers in sequence. It manages its own background processes internally. **Do NOT append `&` to the dev command** — it already backgrounds each server process and polls each port in the correct order.

**IMPORTANT: Write the dev command to a shell script file and execute it.** Do NOT pass multi-line commands to `bash -c` — newlines are lost and the command silently breaks (backgrounded processes, PIDs, loops, and conditionals all fail). Write it to `<work_dir>/start-dev.sh` and run `bash <work_dir>/start-dev.sh`.

1. **Write the dev command to a script file and run it** from the project directory. The script performs these steps internally, in strict order:
   - **Step A**: Starts the webpack dev server on port 9001 in the background
   - **Step B**: Polls port 9001 until it responds (**HTTP 404 / curl exit code 22 is acceptable** — the server returns `Cannot GET /` before the console bridge connects)
   - **Step C**: Starts the console bridge on port 9000 in the background — **this MUST NOT happen before Step B succeeds**
   - **Step D**: Polls port 9000 until it responds with HTTP 200
2. **After the script completes**, verify the dev URL is responsive with `curl -sf`. If it fails, report the error and stop.
3. **Wait an additional 5 seconds** for JS bundles and assets to fully load.
4. **Do not call any `playwright-mcp` tool until all checks above pass.**

**Otherwise** (standard app — single dev server):

**WARNING: Dev servers (`npm start`, `webpack serve`, `npm run dev`) are long-running processes that NEVER exit on their own. If you run them without `&`, your session WILL hang indefinitely and never recover. You MUST background them.**

WRONG — will hang forever:
```bash
cd <project_path> && npm start
```

RIGHT — backgrounds the process:
```bash
cd <project_path>
npm start &
DEV_PID=$!
```

1. Start the dev server **in the background** (append `&`) and capture the process ID as shown above
2. Extract the local URL from the server output (e.g., `http://localhost:3000`)
3. **Poll the URL every 2 seconds, up to 120 seconds**, until it returns a successful response. If it does not respond within 120 seconds, report the error and stop.
4. **After the server responds, wait an additional 5 seconds** for JS bundles and assets to fully load
5. **Do not call any `playwright-mcp` tool until both checks above pass.** Proceeding before the server is ready will cause screenshot failures.

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

Kill the dev server process. Also clean up any console container: `podman stop migration-console okd-console 2>/dev/null || true`

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
