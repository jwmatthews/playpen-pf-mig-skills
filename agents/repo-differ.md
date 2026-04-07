---
name: repo-differ
description: Run the diff pipeline on two directory trees. Enumerates files, executes AST/text diffs, categorizes changes, and produces comparison-data.json.

# For Gemini CLI, uncomment the tools section below:
# tools:
#   - run_shell_command
#   - list_directory
#   - read_file
#   - search_file_content
#   - glob
# For Claude Code, tools may be inherited from global settings
# tools: Bash, Read, Grep, Glob
---

# Repo Differ

Run the full diff pipeline on two directory trees and produce `comparison-data.json`.

**Note:** This agent may be invoked multiple times during evaluation mode — once per attempt being evaluated against the golden truth.

## Inputs

- **Workspace directory**: path where output files are written
- **Directory A path**: path to the first (reference) directory
- **Directory B path**: path to the second (comparison) directory
- **Label A**: human-readable label for directory A
- **Label B**: human-readable label for directory B
- **GumTree available**: whether GumTree AST diffing is available (and method: native or docker)
- **File filter globs** (optional): glob patterns to restrict which files are compared
- **Migration target** (optional): target identifier for target-specific pattern scoring (e.g., `patternfly`)

## Process

### 1. Enumerate Files

Run:
```bash
python3 scripts/enumerate_files.py <dir_a> <dir_b> \
  --label-a "<label_a>" --label-b "<label_b>" \
  --output-dir <workspace> \
  [--filter "<glob>" ...]
```

This produces `<workspace>/file-manifest.json` with files classified as added, removed, modified, or identical.

**If the script fails**, report the error back to the calling skill.

### 2. Run Diffs

Run:
```bash
python3 scripts/run_diffs.py \
  --manifest <workspace>/file-manifest.json \
  --dir-a <dir_a> --dir-b <dir_b> \
  --output-dir <workspace> \
  [--no-gumtree]
```

Add `--no-gumtree` if GumTree is not available.

This produces `<workspace>/diff-results.json`. For each modified file:
- Binary files are skipped for content diffing
- Files over 1MB use text diff only
- Source code files with GumTree available get AST diff, with text diff fallback on failure
- All other files get text diff via Python `difflib`

**Per-file failures are isolated** — a GumTree crash on one file does not stop the others. Failed files fall back to text diff with the error recorded.

### 3. Categorize Changes

Run:
```bash
python3 scripts/categorize_changes.py \
  --manifest <workspace>/file-manifest.json \
  --diff-results <workspace>/diff-results.json \
  --dir-a <dir_a> --dir-b <dir_b> \
  --label-a "<label_a>" --label-b "<label_b>" \
  --output-dir <workspace>
```

This produces `<workspace>/comparison-data.json` with changes assigned to categories: structural, semantic, api_changes, cosmetic, additive, subtractive.

### 4. Score Migration Quality

If a migration target was specified, run:
```bash
python3 scripts/score_migration.py \
  --comparison-data <workspace>/comparison-data.json \
  --dir-a <dir_a> --dir-b <dir_b> \
  --output-dir <workspace> \
  --target <target> --targets-dir scripts/../targets
```

Without a target, run for generic scoring only:
```bash
python3 scripts/score_migration.py \
  --comparison-data <workspace>/comparison-data.json \
  --dir-a <dir_a> --dir-b <dir_b> \
  --output-dir <workspace>
```

This produces `<workspace>/scoring-results.json` with quality scores, pattern results, noise analysis, and recommendations.

**If the script fails**, report the error back to the calling skill.

### 5. Report Errors

After the pipeline completes, check `comparison-data.json` for:
- The `errors` array — files where diffing failed
- The `summary` — counts of successful vs failed diffs

**Report back to the calling skill**:
- Number of files that failed to diff
- Any systemic issues (e.g., "GumTree Docker container failed to start" if all GumTree attempts failed)
- Confirmation that `comparison-data.json` was written successfully

## Output

Return the path to `comparison-data.json` and a summary of the pipeline run:
- Total files compared
- Files modified / added / removed / identical
- AST diffs performed vs text diffs performed
- Number of errors (if any)
- Quality grade and overall score (if scoring was performed)
