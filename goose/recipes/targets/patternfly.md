# PatternFly Migration

PatternFly 5 to PatternFly 6 migration with visual regression testing.

## Workflow

```
Pre-Migration → Phase 2 (Fix Loop) → Phase 3 (E2E Tests) → Visual Comparison → Visual Fix → Done
```

---

## Pre-Migration

**Complete ALL of these steps BEFORE Phase 2. These steps are strictly sequential — each step must complete before the next one starts. Do not parallelize them.** The visual baseline (step 2) must capture the code in its original pre-migration state, before pf-codemods or any other tool modifies the source.

### 1. Discover UI Elements

Invoke `visual_discovery` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1 (e.g., `/tmp/migration-02_10_26_14`)
- `project_path`: path to the project

This creates `$WORK_DIR/manifest.md` with every route, interactive component, theme variant, layout mode, and UI state.

**If the sub-recipe fails or returns without creating `manifest.md`**: retry once. If it fails again, create the manifest yourself by reading the project's route definitions and component files.

### 2. Capture Visual Baseline

For console plugins (`IS_CONSOLE_PLUGIN=true`): read `$WORK_DIR/console-dev-setup.json` and use the console dev command as `dev_command` and the console dev URL as `dev_url`.

Invoke `visual_captures` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1
- `output_dir`: `$WORK_DIR/baseline`
- `project_path`: path to the project
- `dev_command`: console dev command if console plugin, otherwise dev server command from project discovery
- `dev_url`: console dev URL if console plugin (e.g., `http://localhost:9000`), otherwise omit

This captures screenshots for every entry in the manifest and saves them to `$WORK_DIR/baseline/`.

**If the sub-recipe fails or returns with missing screenshots**: start the dev server yourself using `bash $WORK_DIR/start-dev.sh`, verify it's running, then capture the missing screenshots manually using `playwright-mcp`. Stop the dev server with `bash $WORK_DIR/stop-dev.sh` when done.

### 3. Run pf-codemods

```bash
npx @patternfly/pf-codemods@latest <project_path> --v6 --fix
```

This auto-fixes many PF5→PF6 issues. Some will still need manual fixes.

### 4. Upgrade Dependencies

Check `package.json` for all `@patternfly/*` dependencies and upgrade every one of them to `^6.x`. This includes packages like `@patternfly/react-core`, `@patternfly/react-table`, `@patternfly/react-icons`, `@patternfly/patternfly`, and any others the project uses. Then run `npm install`.

Verify build passes after upgrade. Address any obvious issues with the build before moving forward.

---

## During Migration

### Fix Strategy

**Prefer long-term fixes over workarounds.**

Do:

- Use new PF6 APIs and components
- Refactor to match PF6 patterns
- Remove compatibility layers

Avoid:
- Suppressing warnings without fixing
- Using `// @ts-ignore` on deprecated props
- Creating wrappers that preserve old APIs

### Typical Group Order

Adapt based on your findings:

1. **Import paths** - Fix module imports first
2. **Component API changes** - Removed/renamed props
3. **Deprecated API replacements** - Old patterns → new
4. **CSS/Styling** - Class names, design tokens

---

## Post-Migration

**Visual regression testing is required.** Do not skip the visual comparison loop. The migration is incomplete until all visual issues are resolved and every checkbox in the report is checked.

### Visual Regression Loop

Repeat the following loop until no unchecked issues remain. N is the fix round, starting at 0.

**Step 1: Capture screenshots**

For console plugins (`IS_CONSOLE_PLUGIN=true`): read `$WORK_DIR/console-dev-setup.json` and use the console dev command and console dev URL.

Invoke `visual_captures` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1 (same path used for baseline)
- `output_dir`: `$WORK_DIR/post-migration-N` (N = fix round, starting at 0)
- `project_path`: path to the project
- `dev_command`: console dev command if console plugin, otherwise dev server command
- `dev_url`: console dev URL if console plugin, otherwise omit

The manifest at `$WORK_DIR/manifest.md` already exists, so it will reuse it and only capture screenshots.

**If the sub-recipe fails or returns with missing screenshots**: start the dev server yourself using `bash $WORK_DIR/start-dev.sh`, capture the missing screenshots manually using `playwright-mcp`, then stop the dev server with `bash $WORK_DIR/stop-dev.sh`.

**Step 2: Compare**

Invoke `visual_compare` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1
- `compare_dir`: `$WORK_DIR/post-migration-N`

It compares `$WORK_DIR/baseline/` against the compare directory and creates or updates `$WORK_DIR/visual-diff-report.md`.

**If the sub-recipe fails or returns without creating the report**: perform the comparison yourself. For each screenshot in the baseline and post-migration directories, compare file sizes and use Python/PIL to check for pixel differences. Write the results to `$WORK_DIR/visual-diff-report.md`.

**Step 3: Check exit condition**

If all issues in `$WORK_DIR/visual-diff-report.md` are checked (`[x]`) → done, exit loop.

If unchecked (`[ ]`) issues remain → continue to step 4.

**Step 4: Fix**

If unchecked issues remain, invoke `visual_fix` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1
- `post_migration_dir`: `$WORK_DIR/post-migration-N`
- `project_path`: path to the project
- `dev_command`: console dev command if console plugin, otherwise dev server command
- `dev_url`: console dev URL if console plugin, otherwise omit
- `migration_context`: a brief 2-3 line summary of the migration so far — include what technologies are involved and what has been done (e.g., codemods applied, which issue groups are fixed, what remains)

It fixes unchecked items, marks them `[x]` in the report, copies verified screenshots to the post-migration directory, and logs fixes to `$WORK_DIR/visual-fixes.md`.

**Fix ALL issues (major AND minor) before completing migration.** Do not mark minor issues as acceptable.

Increment N and go back to step 1.

### Completion Checklist

- [ ] Visual comparison done
- [ ] ALL visual issues fixed (all checkboxes in report are `[x]`)
- [ ] Migration comments removed
