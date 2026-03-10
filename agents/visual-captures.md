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
- **Dev URL**: the dev server URL, already verified as responsive by the main agent (e.g., `http://localhost:9000`)

## Prerequisites

`<work_dir>/manifest.md` **must exist** before this agent runs. If it is missing, report an error and stop. Use the `visual-discovery` agent to create the manifest first.

## Process

### 1. Read Manifest

Read `<work_dir>/manifest.md` to get the full list of elements to capture. **Every entry in the manifest must be captured.** Do not skip any entry.

### 2. Verify Dev Server

The main agent has already started the dev server and verified it is responsive. Confirm by running:
```bash
curl -sf -o /dev/null <dev_url> 2>/dev/null && echo "READY" || echo "NOT_READY"
```
If `NOT_READY`, **report the error and stop.** Do not attempt to start the dev server yourself — never run `npm start`, `npx webpack serve`, or any other startup command. The main agent is responsible for server lifecycle.

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

### 5. Done

Do not stop the dev server — the main agent manages server lifecycle.

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
