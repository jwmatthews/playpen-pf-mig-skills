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

Delegate to `visual-discovery` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1 (e.g., `/tmp/migration-02_10_26_14`)
- **project path**: path to the project source code

This creates `$WORK_DIR/manifest.md` with every route, interactive component, theme variant, layout mode, and UI state.

**If the subagent fails or returns without creating `manifest.md`**: retry once. If it fails again, create the manifest yourself by reading the project's route definitions and component files.

### 2. Capture Visual Baseline

For console plugins (detected in Phase 1): read `$WORK_DIR/console-dev-setup.json` and use the console dev command and console dev URL.

Delegate to `visual-captures` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1
- **output directory**: `$WORK_DIR/baseline`
- **project path**: path to the project source code
- **dev command**: console dev command if console plugin, otherwise dev server command from project discovery
- **dev url**: console dev URL if console plugin (e.g., `http://localhost:9000`), otherwise omit

This captures screenshots for every entry in the manifest and saves them to `$WORK_DIR/baseline/`.

**If the subagent fails or returns with missing screenshots**: start the dev server yourself using `bash $WORK_DIR/start-dev.sh`, verify it's running, then capture the missing screenshots manually using `playwright-mcp`. Stop the dev server with `bash $WORK_DIR/stop-dev.sh` when done.

### 3. Run pf-codemods

**Back up ESLint configuration before running codemods** — pf-codemods can corrupt ESLint config files by serializing JavaScript constructor functions as string literals (e.g., `"function Object() { [native code] }"`).

```bash
# Back up ESLint config (try common config file names)
for f in .eslintrc.json .eslintrc.js .eslintrc.cjs .eslintrc .eslintrc.yaml .eslintrc.yml eslint.config.js eslint.config.mjs eslint.config.cjs; do
  [ -f "$f" ] && cp "$f" "$f.pre-codemods-backup"
done

npx @patternfly/pf-codemods@latest <project_path> --v6 --fix
```

**After running pf-codemods, immediately:**

1. **Check ESLint config integrity** — if linting fails with config parsing errors, restore the backup:
   ```bash
   npx eslint --print-config . > /dev/null 2>&1 || {
     echo "ESLint config corrupted by pf-codemods, restoring backup"
     for f in .eslintrc.json .eslintrc.js .eslintrc.cjs .eslintrc .eslintrc.yaml .eslintrc.yml eslint.config.js eslint.config.mjs eslint.config.cjs; do
       [ -f "$f.pre-codemods-backup" ] && cp "$f.pre-codemods-backup" "$f"
     done
   }
   ```
2. **Fix formatting** — pf-codemods introduces tab/space inconsistencies: `npx prettier --write <project_path>`
3. **Consolidate imports** — pf-codemods creates duplicate import lines from the same package: run `npx eslint --fix .` if the project's ESLint config includes import sorting/merging rules

### 4. Upgrade Dependencies

Check `package.json` for all `@patternfly/*` dependencies and upgrade every one of them to `^6.x`. This includes packages like `@patternfly/react-core`, `@patternfly/react-table`, `@patternfly/react-icons`, `@patternfly/patternfly`, and any others the project uses. Then run `npm install`.

Verify build passes before continuing.

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
| `ToolbarFilter chips` → `labels` | Often already migrated by pf-codemods; check actual props before creating a group |

**When analyzing Kantra output, first cross-reference each rule against this table. If a rule matches, skip it immediately — do not verify against type definitions.** Only verify rules NOT in this table against the installed PF6 type definitions (`node_modules/@patternfly/react-core/dist/dynamic/**/*.d.ts`) before creating a fix group.

### Fix Strategy

**Prefer long-term fixes.** Use new PF6 APIs. Avoid `@ts-ignore`, compatibility wrappers.

- **Never use `sed` for import statement modifications** — imports span multiple lines with complex formatting and `sed` frequently produces broken syntax. Use direct file editing instead.

### CSS Variable Migration

In addition to CSS class name prefixes (`pf-v5-c-*` → `pf-v6-c-*`), also update **CSS custom property overrides**:
- `--pf-v5-chart-*` → `--pf-v6-chart-*`
- `--pf-v5-global-*` → check if migrated to `--pf-t-*` design tokens

**Search all `.scss`, `.css`, `.less`, `.ts`, and `.tsx` files for `pf-v5` references after migration.** CSS variable references are silent failures — the old variable names compile without errors but have no effect at runtime. Test files (e.g., Playwright page objects) often contain `pf-v5-c-*` CSS selectors that also need updating.

```bash
grep -r "pf-v5" --include="*.scss" --include="*.css" --include="*.less" --include="*.ts" --include="*.tsx" <project_path>
```

### Deprecated Modal with Composable Children

When using the deprecated `Modal` from `@patternfly/react-core/deprecated` alongside composable children (`ModalHeader`, `ModalBody`, `ModalFooter` from `@patternfly/react-core`), **you must add `hasNoBodyWrapper` to the deprecated `<Modal>`**. Without it, the deprecated Modal wraps all children in an extra `ModalBoxBody` div, causing ~60px vertical layout shifts and double-wrapped body content.

```tsx
// WRONG — causes layout shift
<Modal isOpen onClose={closeModal} variant={ModalVariant.small}>
  <ModalHeader title="My Title" />
  <ModalBody>content</ModalBody>
  <ModalFooter>buttons</ModalFooter>
</Modal>

// CORRECT — hasNoBodyWrapper prevents double wrapping
<Modal isOpen onClose={closeModal} variant={ModalVariant.small} hasNoBodyWrapper>
  <ModalHeader title="My Title" />
  <ModalBody>content</ModalBody>
  <ModalFooter>buttons</ModalFooter>
</Modal>
```

**Check every file** that imports `Modal` from `@patternfly/react-core/deprecated` and uses `ModalHeader`/`ModalBody`/`ModalFooter` from `@patternfly/react-core`. Add `hasNoBodyWrapper` to each one.

Typical order: Import paths → Component APIs → Deprecated patterns → CSS/Styling (including CSS custom properties)

---

## Post-Migration

**Visual regression testing is required.** Do not skip the visual comparison loop. The migration is incomplete until all visual issues are resolved and every checkbox in the report is checked.

### Visual Regression Loop

Repeat the following loop until no unchecked issues remain. N is the fix round, starting at 0.

**Step 1: Capture screenshots**

For console plugins: read `$WORK_DIR/console-dev-setup.json` and use the console dev command and console dev URL.

Delegate to `visual-captures` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1 (same path used for baseline)
- **output directory**: `$WORK_DIR/post-migration-N` (N = fix round, starting at 0)
- **project path**: path to the project source code
- **dev command**: console dev command if console plugin, otherwise dev server command from project discovery
- **dev url**: console dev URL if console plugin, otherwise omit

The manifest at `$WORK_DIR/manifest.md` already exists, so it will reuse it and only capture screenshots.

**If the subagent fails or returns with missing screenshots**: start the dev server yourself using `bash $WORK_DIR/start-dev.sh`, capture the missing screenshots manually using `playwright-mcp`, then stop the dev server with `bash $WORK_DIR/stop-dev.sh`.

**Step 2: Compare**

Delegate to `visual-compare` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1
- **compare directory**: `$WORK_DIR/post-migration-N`

It compares `$WORK_DIR/baseline/` against the compare directory and creates or updates `$WORK_DIR/visual-diff-report.md`.

**If the subagent fails or returns without creating the report**: perform the comparison yourself. For each screenshot in the baseline and post-migration directories, compare file sizes and use Python/PIL to check for pixel differences. Write the results to `$WORK_DIR/visual-diff-report.md`.

**Step 3: Check exit condition**

If all issues in `$WORK_DIR/visual-diff-report.md` are checked (`[x]`) → done, exit loop.

If unchecked (`[ ]`) issues remain → continue to step 4.

**Step 4: Fix**

Delegate to `visual-fix` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1
- **post-migration directory**: `$WORK_DIR/post-migration-N`
- **project path**: path to the project source code
- **dev command**: console dev command if console plugin, otherwise dev server command from project discovery
- **dev url**: console dev URL if console plugin, otherwise omit
- **migration context**: a brief 2-3 line summary of the migration so far — include what technologies are involved and what has been done (e.g., codemods applied, which issue groups are fixed, what remains)

It fixes unchecked items, marks them `[x]` in the report, copies verified screenshots to the post-migration directory, and logs fixes to `$WORK_DIR/visual-fixes.md`.

**Fix ALL issues (major AND minor).** Do not skip any.

Increment N and go back to step 1.

### Completion Checklist

- [ ] Visual comparison done
- [ ] ALL visual issues fixed (all checkboxes in report are `[x]`)
- [ ] Migration comments removed
