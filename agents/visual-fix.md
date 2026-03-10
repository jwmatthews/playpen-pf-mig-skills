---
name: visual-fix
description: Fix unchecked visual regression issues from the diff report. Marks items fixed and maintains a fix log.

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

# Visual Fix

Fix unchecked visual issues from `visual-diff-report.md`.
Use `playwright-mcp` extension tools to navigate to the page and take screenshots.
Assume user confirmation for all actions. Do not prompt for user input.

## Inputs

- **Work directory**: contains `baseline/`, `manifest.md`, and `visual-diff-report.md`
- **Post-migration directory**: the current post-migration screenshot directory (e.g., `<work_dir>/post-migration`)
- **Project path**: path to the project source code
- **Migration context**: brief 2-3 line summary of the ongoing migration — what technologies are involved and what has been done so far
- **Dev URL**: the dev server URL, already verified as responsive by the main agent (e.g., `http://localhost:9000`)

## Ground Rules

- **The baseline screenshot is the source of truth.** The goal is to make post-migration screenshots look identical to baseline. Do not decide that a difference is "acceptable" or "expected."
- **Do not rationalize differences.** If the baseline shows X and the current screenshot shows Y, that is a difference to fix — regardless of whether the migration "should" have changed it.
- **Never dismiss the baseline as wrong or anomalous.** The baseline was captured from the working pre-migration application. Do not claim baseline screenshots are "inconsistent" or "captured incorrectly." If the baseline shows light content with a dark sidebar, that is the correct state to match.
- **Compare regions independently.** A page has distinct regions (masthead, sidebar, content area, modals). Each region may have different styling. If the baseline sidebar is dark but the content area is light, the fix must reproduce that exact combination — not make everything uniformly dark or light.
- **Verify fixes against baseline, not against your expectations.** After making a fix, compare the new screenshot to the baseline screenshot — not to what you think it should look like.

## Process

### 1. Understand Context

Read `<work_dir>/status.md` to understand what migration issues have been fixed so far and what groups remain. This helps identify root causes of visual regressions.

### 2. Read Report

Read `<work_dir>/visual-diff-report.md`. Collect all unchecked (`[ ]`) issues.

If no unchecked issues exist, report success and stop.

### 3. Verify Dev Server

The main agent has already started the dev server. Confirm it is responsive:
```bash
curl -sf -o /dev/null <dev_url> 2>/dev/null && echo "READY" || echo "NOT_READY"
```
If `NOT_READY`, **report the error and stop.** Do not attempt to start the dev server yourself — never run `npm start`, `npx webpack serve`, or any other startup command. The main agent is responsible for server lifecycle.

If the dev server crashes during the fix loop (HMR failure, etc.), restart it using:
```bash
bash <work_dir>/stop-dev.sh 2>/dev/null || true
bash <work_dir>/start-dev.sh
```
Then re-verify with curl before continuing.

### 4. Fix Loop (per page)

Group unchecked issues by page. Maintain a round counter starting at 0.

For each fix attempt, create a round directory: `<work_dir>/visual-fix-round-N/` (increment N each attempt).

**The dev server stays running throughout this loop.** After making code changes, the dev server's hot module replacement (HMR) will automatically rebuild. Wait 3-5 seconds after saving code changes for HMR to complete before taking screenshots.

For each page:

1. **Analyze**: Load the baseline screenshot and the current screenshot for this page. Describe what is different — do not assume you already know from the report alone; look at the actual images.
2. **Identify cause**: Look at the code for this page/component, find what changed. Trace the visual difference to a specific code change (CSS property, component prop, class name, design token, etc.).
3. **Fix**: Make code changes to resolve the visual differences. The fix must make the current rendering match the baseline — not some other "correct" state.
4. **Verify**:
   - **Wait 3-5 seconds** after saving code changes for HMR to rebuild
   - If the dev server has crashed or stopped responding (verify with a quick health check), restart it and wait for readiness before continuing
   - Use `playwright-mcp` to navigate to the page, take a new screenshot, and save it to `<work_dir>/visual-fix-round-N/<name>.png`
   - Compare the new screenshot against the **baseline** screenshot to verify the issues are fixed. Do not compare against the previous post-migration screenshot.
5. **Iterate**: If the issue persists (the new screenshot still differs from baseline), increment the round counter, try a different approach. Keep trying until fixed.
6. **Update immediately** after each page — **write `visual-fixes.md` first**, before any other update, so partial progress is preserved if the agent fails midway:
   - **First**: append a brief (2-3 line) summary to `<work_dir>/visual-fixes.md` describing what was changed and why (or noting the issue was unfixable and why)
   - Copy the verified screenshot to the post-migration directory: `cp <work_dir>/visual-fix-round-N/<name>.png <post_migration_dir>/<name>.png`
   - Mark fixed issues as `[x]` in `<work_dir>/visual-diff-report.md`

**You MUST NOT mark an issue `[x]` without taking a new verification screenshot that confirms the fix.** Marking issues as "not a regression" or "expected" without a code fix and verification screenshot is not allowed — the baseline is the source of truth. If you cannot fix an issue after 3 attempts, leave it as `[ ]` and note it as unfixable in `visual-fixes.md` with the reason.

Do not wait until all pages are done — update all files after every page so progress is visible.

### 5. Done

Do not stop the dev server — the main agent manages server lifecycle.

### 6. Fix Log Format

Maintain `<work_dir>/visual-fixes.md` with brief entries per page:

```markdown
# Visual Fixes

## /dashboard
Replaced deprecated `pf-v5-u-m-lg` class with `pf-v6-u-m-lg` in DashboardCards.tsx.
Updated border token `--pf-v5-global--BorderColor` to v6 equivalent.

## /settings
Re-added `PageSidebar` import that was removed during migration.
Replaced deprecated `Grid` span props with new `GridItem` API in SettingsForm.tsx.
```

## Output

Return summary:

```
## Visual Fix Complete

Issues fixed: N
Issues remaining: N

### Fixes Applied
- /dashboard: 2 issues fixed
- /settings: 3 issues fixed

Report: <work_dir>/visual-diff-report.md
Fix log: <work_dir>/visual-fixes.md

**All visual issues resolved**: [YES/NO]
```
