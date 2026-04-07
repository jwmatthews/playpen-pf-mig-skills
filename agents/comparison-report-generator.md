---
name: comparison-report-generator
description: Enrich comparison data with natural-language annotations and generate the HTML comparison report.

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
# tools: Bash, Read, Write, Edit, Grep, Glob
---

# Comparison Report Generator

Enrich comparison data with migration-context annotations and generate the final HTML report.

## Inputs

- **Workspace directory**: path containing `comparison-data.json`
- **Label A**: human-readable label for reference A
- **Label B**: human-readable label for reference B

## Process

### 1. Read Comparison Data

Read `<workspace>/comparison-data.json`. Understand the overall shape:
- How many files were modified, added, removed
- What change categories are present
- What errors occurred (if any)

### 2. Annotate Significant Changes

For the **top ~20 most significant changes** (prioritize by: api_changes first, then semantic, then structural, then additive/subtractive — skip cosmetic), do the following:

1. Read the source files from both directories (paths are in `metadata.repo_a.path` and `metadata.repo_b.path`)
2. Read the `text_diff` for the file from `comparison-data.json`
3. Write a **concise natural-language annotation** (1-3 sentences) describing what changed in migration context. Focus on:
   - What API was changed and why it matters
   - What behavior changed
   - Whether the change looks intentional or accidental
   - How it compares between the two references

Add each annotation to the `annotations` array in `comparison-data.json`:
```json
{
  "path": "src/App.tsx",
  "text": "Changed PageSection variant from 'light' to 'default' — this is the PF6 equivalent of the deprecated 'light' variant."
}
```

### 3. Write Updated Data

Write the updated `comparison-data.json` with the annotations added.

### 4. Generate HTML Report

Run:
```bash
python3 scripts/generate_comparison_report.py <workspace>
```

This produces `<workspace>/comparison-report.html`.

### 5. Verify Report

Confirm that `comparison-report.html` exists and is non-empty.

## Output

Return the path to `comparison-report.html`:
```
Report generated: <workspace>/comparison-report.html
```
