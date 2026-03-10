---
name: visual-compare
description: Compare screenshots between baseline and post-migration directories. Generates or updates a checkbox-tracked report.

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

# Visual Comparison

Compare screenshots between baseline and post-migration directories. Generate or update a checkbox-tracked report.

## Inputs

- **Work directory**: workspace root (contains `baseline/`, `manifest.md`, and `visual-diff-report.md`)
- **Compare directory**: directory with post-migration screenshots to compare against baseline

## Prerequisites

Verify these exist before proceeding:
- `<work_dir>/manifest.md`
- `<work_dir>/baseline/` with screenshots

If either is missing, report error and stop.

## Ground Rules

- **The baseline screenshot is the source of truth.** The post-migration screenshot must look identical to it.
- **Do not rationalize differences.** If something looks different, it IS different. Do not explain away a difference as "expected due to the migration" or "acceptable styling variation."
- **Report every visible difference**, no matter how small. A slightly different shade, a font weight change — all are differences and must be reported.
- **When in doubt, report it.** False positives are acceptable. Missed differences are not.
- **You MUST visually inspect every screenshot yourself.** Do not write scripts, use PIL, ImageMagick, or any automated pixel-diffing tool as a substitute for looking at the images. You are a multimodal model — read the image files directly and describe what you see. Automated tools miss structural and content differences.
- **Compare regions independently.** A page has distinct regions (masthead, sidebar, content area, modals). Each region may have different styling. Check each region's colors against the baseline — do not summarize the page as "all dark" or "all light."

### Efficiency

- **Load each image only once.** When comparing a pair of screenshots, read both files in a single step or back-to-back, then perform all analysis from those reads. Do not re-load the same image file multiple times for different analysis passes.
- **Batch your reads.** If your runtime supports parallel tool calls, load multiple image pairs in parallel rather than sequentially.

### Subpixel / Anti-aliasing Noise

Differences where fewer than 0.5% of pixels differ **and** the maximum per-channel difference is ≤ 15 are almost certainly font anti-aliasing artifacts from the rendering engine. **Do not report these as issues.** Instead, list them in a separate "Identical (within anti-aliasing tolerance)" section at the end of the report — no checkboxes, just a note. This avoids generating dozens of unfixable items that waste time in the fix phase.

## Process

### 1. Run Pixel Comparison Script

Run the automated comparison first to identify which screenshots have real differences:
```bash
python3 <scripts_dir>/compare_screenshots.py <work_dir>/baseline <compare_dir> > <work_dir>/pixel-comparison.json
```
If the script is not found, look for `compare_screenshots.py` in the workspace or scripts directory.

Read the JSON output. Screenshots with status `identical` or `anti_aliasing_only` need no further analysis. **Only visually inspect screenshots with status `different` or `missing_post_migration`.**

### 2. Verify Coverage

Read `<work_dir>/manifest.md`. Check the pixel comparison results for any `missing_post_migration` or `missing_baseline` entries. Report each as a `❌ Major` issue.

### 3. Visually Inspect Changed Screenshots

**Only for screenshots flagged as `different` by the pixel comparison script**, load the baseline and post-migration images. Load each image exactly once.

For each changed screenshot:

1. **Load both images**: baseline and post-migration — one read each
1a. **Verify page content matches the manifest description.** If the post-migration screenshot shows wrong content (404 page, different page, empty state), report as `❌ Major`.
2. **Describe what changed**: Use the pixel comparison `diff_regions` to focus on areas with actual differences. Describe the specific visual changes you see.
3. **Classify each difference**:
   - ⚠️ Minor — styling/spacing/color changes that do not break functionality
   - ❌ Major — missing elements, broken layout, unreadable text, functional breakage

**Both minor and major issues require fixes.** Do not dismiss minor issues as acceptable.

### 3. Write Report

Create or update `<work_dir>/visual-diff-report.md`.

**If the report does NOT exist**, create it with all issues as unchecked:

```markdown
# Visual Comparison Report

Compared: <timestamp>
Baseline: <work_dir>/baseline
Post-migration: <compare_dir>

## Issues

### /dashboard
- [ ] Card spacing increased ~4px (⚠️ Minor)
- [ ] Button borders slightly darker (⚠️ Minor)

### /settings
- [ ] Navigation sidebar missing (❌ Major)
- [ ] Form layout broken - fields overlap (❌ Major)
- [ ] Submit button not visible (❌ Major)
```

**If the report already exists**, update it:
1. For each previously reported issue: if now fixed (screenshots match), change `[ ]` to `[x]`
2. For any new issues found: append as `[ ]` under the appropriate page heading

Pages with no issues should NOT appear in the report.

## Output

Return the report summary:

```
## Visual Comparison Complete

| Status | Count |
|--------|-------|
| ✓ No issues | N |
| ⚠️ Minor | N |
| ❌ Major | N |
| ✅ Previously fixed | N |

Unchecked issues remaining: N

Report: <work_dir>/visual-diff-report.md

**Action Required**: [YES - N unchecked issues remain / NO - all resolved]
```
