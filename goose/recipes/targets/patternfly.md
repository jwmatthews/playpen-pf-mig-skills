# PatternFly Migration

PatternFly 5 to PatternFly 6 migration with visual regression testing.

## Workflow

```
Pre-Migration → Phase 2 (Fix Loop) → Phase 3 (E2E Tests) → Visual Comparison → Visual Fix → Done
```

---

## Pre-Migration

**Complete ALL of these steps BEFORE Phase 2. These steps are strictly sequential — each step must complete before the next one starts. Do not parallelize them.** The visual baseline (step 2) must capture the code in its original pre-migration state, before any tool modifies the source.

### 1. Discover UI Elements

Invoke `visual_discovery` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1 (e.g., `/tmp/migration-02_10_26_14`)
- `project_path`: path to the project

This creates `$WORK_DIR/manifest.md` with every route, interactive component, theme variant, layout mode, and UI state.

**If the sub-recipe fails or returns without creating `manifest.md`**: retry once. If it fails again, create the manifest yourself by reading the project's route definitions and component files.

### 2. Capture Visual Baseline

**Start the dev server before invoking the sub-recipe.** The sub-recipe only captures screenshots — it does not start or stop servers.

```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
bash $WORK_DIR/start-dev.sh
```

For console plugins (`IS_CONSOLE_PLUGIN=true`): read `$WORK_DIR/console-dev-setup.json` and use the console dev URL. Otherwise, determine the dev URL from the start script output or project configuration.

Verify the dev URL is responsive before invoking the sub-recipe:
```bash
curl -sf -o /dev/null <dev_url> && echo "READY" || echo "NOT READY"
```

Invoke `visual_captures` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1
- `output_dir`: `$WORK_DIR/baseline`
- `dev_url`: the verified dev URL (e.g., `http://localhost:9000`)

This captures screenshots for every entry in the manifest and saves them to `$WORK_DIR/baseline/`.

**If the sub-recipe fails or returns with missing screenshots**: capture the missing screenshots manually using `playwright-mcp` (the dev server is still running).

**After capture is complete**, stop the dev server:
```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
```

### 3. Upgrade Dependencies

Check `package.json` for all `@patternfly/*` dependencies and upgrade every one of them to `^6.x`. This includes packages like `@patternfly/react-core`, `@patternfly/react-table`, `@patternfly/react-icons`, `@patternfly/patternfly`, and any others the project uses. Then run `npm install`.

Verify build passes after upgrade. Address any obvious issues with the build before moving forward.

---

## During Migration

### Known Kantra False Positives for PF6

The following Kantra rules produce false positives for PF6 6.x. **Do not create fix groups for these. Do not re-verify them against type definitions — they have already been verified. Simply list them in status.md as false positives and move on.**

| Kantra Rule Pattern | Why False Positive |
|---|---|
| `header=` → `masthead=` | Matches ANY `header` JSX prop, not just `Page.header` |
| Deep import path restructuring | PF6 barrel imports from `@patternfly/react-core` work correctly |
| `isOpen` → `open` | PF6 Select/Dropdown/Popover still use `isOpen` |
| `isDisabled` → `disabled` | PF6 TextInput/Button/Select still use `isDisabled` |
| `isExpanded` → `expanded` | PF6 ExpandableSection/MenuToggle still use `isExpanded` |
| `isSelected` removal | PF6 MenuItem/SelectOption still use `isSelected` |
| `isActive` → `active` | PF6 NavItem still uses `isActive` |
| `spaceItems` removal | PF6 Flex still supports `spaceItems` |
| `spacer` → `gap` | PF6 Flex/FlexItem still supports `spacer` (both `spacer` and `gap` work) |
| `ButtonVariant.link` → `plain` | PF6 still has `link` variant |
| `ButtonVariant.control` → `plain` | PF6 still has `control` variant |
| `alignRight` → `alignEnd` | PF6 FlexItem `align` still accepts `alignRight` |
| Modal `title` → `titleText` | Matches `title` on `ModalHeader` (the correct new API), not deprecated `Modal.title` |
| `ErrorState` prop renames | Often a custom project component, not PF's `ErrorState` from `react-component-groups` |
| `CardHeader selectableActions` | Often already using the correct PF6 `selectableActions` object API |
| `ToolbarFilter chips` → `labels` | Often already using the correct PF6 `labels` prop; check actual props before creating a group |

**These false positives are automatically removed by `filter_kantra_false_positives.py`.** Always run the filter script on Kantra output before analysis — the filtered output will only contain real issues. If you see any of the above patterns in filtered output, they were not caught by the filter; skip them manually.

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
- **Using `sed` for import statement modifications** — imports span multiple lines with complex formatting and `sed` frequently produces broken syntax. Use direct file editing instead.

### CSS Variable Migration

In addition to CSS class name prefixes (`pf-v5-c-*` → `pf-v6-c-*`), also update:
- **CSS custom property overrides**: `--pf-v5-chart-*` → `--pf-v6-chart-*`, `--pf-v5-global-*` → check if migrated to `--pf-t-*` design tokens
- **Theme CSS classes**: `pf-v5-theme-dark` → `pf-v6-theme-dark` (dark theme will not apply if the old class name is used)

**Search all `.scss`, `.css`, `.less`, `.ts`, and `.tsx` files for `pf-v5` references after migration.** CSS variable references are silent failures — the old variable names compile without errors but have no effect at runtime. Test files (e.g., Playwright page objects) often contain `pf-v5-c-*` CSS selectors that also need updating.

```bash
grep -r "pf-v5" --include="*.scss" --include="*.css" --include="*.less" --include="*.ts" --include="*.tsx" <project_path>
```

### 4. Fix Deprecated Modal with Composable Children

**Run this immediately after upgrading dependencies (step 3).** When `Modal` is moved to `@patternfly/react-core/deprecated`, `hasNoBodyWrapper` must be added. Without it, the deprecated Modal wraps all children in an extra `ModalBoxBody` div, causing ~60px vertical layout shifts.

```bash
python3 <recipe_dir>/scripts/fix_deprecated_modal_wrapper.py <project_path>
```

This automatically finds all `.tsx`/`.jsx` files that import `Modal` from `@patternfly/react-core/deprecated` with composable children (`ModalHeader`/`ModalBody`/`ModalFooter`) and adds `hasNoBodyWrapper` to each `<Modal>` tag. Review the JSON output to see which files were fixed.

### Typical Group Order

Adapt based on your findings:

1. **Import paths** - Fix module imports first
2. **Component API changes** - Removed/renamed props
3. **Deprecated API replacements** - Old patterns → new
4. **CSS/Styling** - Class names, design tokens, CSS custom properties

---

## Post-Migration

**Visual regression testing is required.** Do not skip the visual comparison loop. The migration is incomplete until all visual issues are resolved and every checkbox in the report is checked.

### Visual Regression Loop

Repeat the following loop until no unchecked issues remain. N is the fix round, starting at 0.

**Step 1: Capture screenshots**

**Start the dev server before invoking the sub-recipe:**
```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
bash $WORK_DIR/start-dev.sh
```
Verify the dev URL is responsive before proceeding.

Invoke `visual_captures` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1 (same path used for baseline)
- `output_dir`: `$WORK_DIR/post-migration-N` (N = fix round, starting at 0)
- `dev_url`: the verified dev URL

The manifest at `$WORK_DIR/manifest.md` already exists, so it will reuse it and only capture screenshots.

**If the sub-recipe fails or returns with missing screenshots**: capture the missing screenshots manually using `playwright-mcp` (the dev server is still running).

**After capture is complete**, stop the dev server:
```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
```

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

**Start the dev server before invoking the sub-recipe:**
```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
bash $WORK_DIR/start-dev.sh
```
Verify the dev URL is responsive before proceeding.

If unchecked issues remain, invoke `visual_fix` sub-recipe with:
- `work_dir`: the `$WORK_DIR` path created in Phase 1
- `post_migration_dir`: `$WORK_DIR/post-migration-N`
- `project_path`: path to the project
- `dev_url`: the verified dev URL
- `migration_context`: a brief 2-3 line summary of the migration so far — include what technologies are involved and what has been done (e.g., which issue groups are fixed, what remains)

It fixes unchecked items, marks them `[x]` in the report, copies verified screenshots to the post-migration directory, and logs fixes to `$WORK_DIR/visual-fixes.md`.

**After fix is complete**, stop the dev server:
```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
```

**Fix ALL issues (major AND minor) before completing migration.** Do not mark minor issues as acceptable.

Increment N and go back to step 1.

### Completion Checklist

- [ ] Visual comparison done
- [ ] ALL visual issues fixed (all checkboxes in report are `[x]`)
- [ ] Migration comments removed
