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

Find every UI element and important state that needs to be captured. **Every navigable route must appear in the manifest. When in doubt, include it. Do not create combinatorial entries — capture each route once in its default state and theme/layout variants only on one representative page.**

**Routes/Pages:**
- Search for router config, route arrays, path definitions, `<Route>` elements
- Check `pages/`, `views/`, `routes/`, `screens/`, `app/` folders
- Find menus, sidebars, navbars, breadcrumbs, footer links and extract all link targets
- Identify parameterized routes and note sample data needed
- Find error pages (404, 500, error boundary)
- **Do not stop after finding the router config.** Cross-reference with navigation components to catch routes that exist in menus but not in the router (and vice versa).
- **Each route gets one manifest entry** in its default state.

**Interactive Components — group similar instances and pick one representative per type.** If an app has 5 modals using the same component with different fields, capture one. A regression in the shared component will show up in any instance.
- Modals/Dialogs — **one representative per distinct layout** (e.g., one form modal, one confirmation modal). Do not capture every variation separately.
- Drawers/Sidepanels — one representative if they share a component
- Dropdown menus — **one representative per distinct type** (e.g., one kebab menu, one type selector). Not every individual menu.
- Forms — one representative if multiple forms share the same layout
- Tabs — only if tab panels have visually distinct structure

**Theme and Layout Variants:**
Check whether the application supports theme switching (light/dark) or layout toggles (sidebar collapsed/expanded). Search for `ThemeProvider`, theme context, `prefers-color-scheme`, `dark`/`light` class toggles, toggle buttons in headers/footers, `localStorage`/`sessionStorage` keys.

- **If themes exist**: pick **one representative page** (the most visually complex) and add a dark-theme variant for that page only.
- **If sidebar collapse exists**: pick **one representative page** and add a collapsed-sidebar variant.
- **Do not multiply every route by every variant.**

**Authentication:** Check whether the application requires login. Look for login pages, auth guards, hardcoded credentials in seed files, `.env.example`, test fixtures, or README instructions. Record any credentials needed.

Create `$WORK_DIR/manifest.md`. Each entry must describe exactly what to capture and how to reach the target state:
```markdown
# UI Manifest
Project: <project_path>

## Routes

### / → home.png
- **Navigate to**: root URL (`/`)
- **Wait for**: page content to fully render
- **Key elements**: sidebar navigation, stats cards, data table

### /dashboard → dashboard.png
- **Navigate to**: `/dashboard`
- **Wait for**: all dashboard widgets to load
- **Key elements**: chart area, summary cards, recent activity list

## Interactive Components

### Modal: Confirm Delete → modal-confirm-delete.png
- **Trigger**: on `/dashboard`, click delete button on any table row
- **Wait for**: modal to appear and content to render
- **Key elements**: modal title, confirmation message, Cancel and Confirm buttons

## Theme/Layout Variants

### /dashboard (dark theme) → dashboard--dark.png
- **Navigate to**: `/dashboard`
- **Setup**: activate dark theme via [describe how]
- **Wait for**: theme transition to complete
- **Key elements**: same as dashboard.png but in dark theme

```

**Naming**: `/` → `home.png`, `/dashboard` → `dashboard.png`. Variants: `dashboard--dark.png`, `dashboard--sidebar-collapsed.png`. Components: `modal-<name>.png`, `drawer-<name>.png`, `tabs-<context>-<tab>.png`, `form-<name>.png`.

### 2. Capture Visual Baseline

1. **Start dev server** using the scripts created during Phase 1:
   ```bash
   bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
   bash $WORK_DIR/start-dev.sh
   ```
   Verify the dev URL is responsive with `curl -sf -o /dev/null <dev_url>`. **Do not call any `playwright-mcp` tool until the server responds.**

2. **Capture screenshots** - For each element in manifest, use `playwright-mcp`:
   - Navigate to page or trigger component (follow any **Setup** steps in the manifest entry)
   - Wait for content to stabilize
   - Take screenshot → save to `$WORK_DIR/baseline/<name>.png`

3. **Verify** - Compare the list of `.png` files in `$WORK_DIR/baseline/` against manifest entries. Every manifest entry must have a corresponding screenshot.

4. **Stop dev server**: `bash $WORK_DIR/stop-dev.sh 2>/dev/null || true`

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

This auto-fixes many PF5→PF6 issues. Some will still need manual fixes.

### 4. Upgrade Dependencies

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
| `ToolbarFilter chips` → `labels` | Often already migrated by pf-codemods; check actual props before creating a group |

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

In addition to CSS class name prefixes (`pf-v5-c-*` → `pf-v6-c-*`), also update **CSS custom property overrides**:
- `--pf-v5-chart-*` → `--pf-v6-chart-*`
- `--pf-v5-global-*` → check if migrated to `--pf-t-*` design tokens

**Search all `.scss`, `.css`, `.less`, `.ts`, and `.tsx` files for `pf-v5` references after migration.** CSS variable references are silent failures — the old variable names compile without errors but have no effect at runtime. Test files (e.g., Playwright page objects) often contain `pf-v5-c-*` CSS selectors that also need updating.

```bash
grep -r "pf-v5" --include="*.scss" --include="*.css" --include="*.less" --include="*.ts" --include="*.tsx" <project_path>
```

### 5. Fix Deprecated Modal with Composable Children

**Run this immediately after upgrading dependencies (step 4).** pf-codemods moves `Modal` to `@patternfly/react-core/deprecated` but does not add `hasNoBodyWrapper`. Without it, the deprecated Modal wraps all children in an extra `ModalBoxBody` div, causing ~60px vertical layout shifts.

```bash
python3 <scripts_dir>/fix_deprecated_modal_wrapper.py <project_path>
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

Read `$WORK_DIR/manifest.md` (already created during pre-migration).

1. **Start dev server**:
   ```bash
   bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
   bash $WORK_DIR/start-dev.sh
   ```
   Verify the dev URL is responsive. **Do not call any `playwright-mcp` tool until the server responds.**
2. **Capture screenshots** - For each element in manifest, use `playwright-mcp`:
   - Navigate to page or trigger component
   - Wait for content to stabilize
   - Take screenshot → save to `$WORK_DIR/post-migration-N/<name>.png` (N = fix round, starting at 0)
3. **Stop dev server**: `bash $WORK_DIR/stop-dev.sh 2>/dev/null || true`

**Step 2: Compare**

Compare `$WORK_DIR/baseline/` against `$WORK_DIR/post-migration-N/`.

**Ground rules:** Baseline is the source of truth. Report every visible difference. Do not rationalize differences. Compare regions independently (masthead, sidebar, content, modals).

**Step 2a: Run pixel comparison script** to identify which screenshots have real differences:
```bash
python3 <scripts_dir>/compare_screenshots.py $WORK_DIR/baseline $WORK_DIR/post-migration-N > $WORK_DIR/pixel-comparison.json
```
Read the JSON output. Screenshots with status `identical` or `anti_aliasing_only` need no further analysis. **Only visually inspect screenshots with status `different` or `missing_post_migration`.**

**Step 2b: Visually inspect changed screenshots only.** For each screenshot flagged as `different`:

1. **Load both images** — baseline and post-migration — one read each
1a. **Verify page content matches the manifest description.** If the post-migration screenshot shows wrong content (404 page, different page, empty state), report as `❌ Major`.
2. **Describe what changed**: Use the pixel comparison `diff_regions` to focus on areas with actual differences. Describe the specific visual changes you see.
3. **Classify each difference**: ⚠️ Minor (styling/spacing/color) / ❌ Major (missing elements, broken layout, functional breakage)

**Both minor and major issues require fixes.** Do not dismiss minor issues as acceptable.

**Create or update report** - Write `$WORK_DIR/visual-diff-report.md` with checkbox-tracked issues:

```markdown
# Visual Comparison Report

## Issues

### /dashboard
- [ ] Card spacing increased ~4px (⚠️ Minor)
- [ ] Button borders slightly darker (⚠️ Minor)

### /settings
- [ ] Navigation sidebar missing (❌ Major)
```

If the report already exists: mark fixed issues as `[x]`, add new issues as `[ ]`.

**Step 3: Check exit condition**

If all issues in `$WORK_DIR/visual-diff-report.md` are checked (`[x]`) → done, exit loop.

If unchecked (`[ ]`) issues remain → continue to step 4.

**Step 4: Fix**

**Ground rules:** Baseline is the source of truth. Do not rationalize differences. Compare regions independently. Verify fixes by taking a screenshot and comparing to baseline. Do not create CSS override files — fix root causes. Do not write PIL/pixel analysis scripts.

Read `$WORK_DIR/status.md` to understand what migration issues have been fixed so far. This helps identify root causes of visual regressions.

**Start the dev server once** and keep it running for the entire fix process:
```bash
bash $WORK_DIR/stop-dev.sh 2>/dev/null || true
bash $WORK_DIR/start-dev.sh
```
Verify the dev URL is responsive. **Do not call any `playwright-mcp` tool until the server responds.**

Fix unchecked issues by page/route. **The dev server stays running throughout.** After making code changes, the dev server's hot module replacement (HMR) will automatically rebuild. Wait 3-5 seconds after saving code changes for HMR to complete before taking screenshots.

1. **Group unchecked issues by page**
2. **For each page with unchecked issues**:
   - Load the baseline screenshot and the current screenshot. Describe what is different — do not assume you already know from the report alone; look at the actual images.
   - Identify cause in code — trace the visual difference to a specific code change (CSS property, component prop, class name, design token, etc.)
   - Make code changes to resolve. The fix must make the current rendering match the baseline.
   - Verify:
     - **Wait 3-5 seconds** after saving code changes for HMR to rebuild
     - If the dev server has crashed or stopped responding (verify with a quick health check), restart it and wait for readiness before continuing
     - Use `playwright-mcp` to navigate to the page, take new screenshot
     - Compare the new screenshot against the **baseline** screenshot. Do not compare against the previous post-migration screenshot.
   - If the issue persists (new screenshot still differs from baseline), try a different approach. Keep trying until fixed.
   - **First**: append a brief (2-3 line) summary to `$WORK_DIR/visual-fixes.md` describing what was changed and why (or noting the issue was unfixable and why). Write this before any other update so partial progress is preserved if the agent fails midway.
   - Copy the verified screenshot to the post-migration directory: `cp` the screenshot to `$WORK_DIR/post-migration-N/<name>.png`
   - Mark fixed issues as `[x]` in `$WORK_DIR/visual-diff-report.md`
   - Do not wait until all pages are done.

**You MUST NOT mark an issue `[x]` without taking a new verification screenshot that confirms the fix.** Marking issues as "not a regression" or "expected" without a code fix and verification screenshot is not allowed — the baseline is the source of truth. If you cannot fix an issue after 3 attempts, leave it as `[ ]` and note it as unfixable in `visual-fixes.md` with the reason.

3. **Stop the dev server** after all pages have been processed: `bash $WORK_DIR/stop-dev.sh 2>/dev/null || true`

**Fix ALL issues (major AND minor) before completing migration.** Do not dismiss minor issues as acceptable.

Increment N and go back to step 1.

### Completion Checklist

- [ ] Visual comparison done
- [ ] ALL visual issues fixed (all checkboxes in report are `[x]`)
- [ ] Migration comments removed
