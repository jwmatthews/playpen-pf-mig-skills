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

1. **Start application and wait** - **The application MUST be running and fully responsive before any `playwright-mcp` interaction.** Playwright operations will fail if the server is not ready.

   **If `IS_CONSOLE_PLUGIN=true`** (multi-stage startup): Read `$WORK_DIR/console-dev-setup.json` for the console dev command and dev URL. **Run the dev command as a foreground script** (do NOT append `&` — it manages its own background processes). The script performs these steps internally, in strict order:
   - **Step A**: Starts the webpack dev server on port 9001 in the background
   - **Step B**: Polls port 9001 until it responds (**HTTP 404 / curl exit code 22 is acceptable** — the server returns `Cannot GET /` before the console bridge connects)
   - **Step C**: Starts the console bridge on port 9000 in the background — **this MUST NOT happen before Step B succeeds**
   - **Step D**: Polls port 9000 until it responds with HTTP 200

   After the script completes, verify the console dev URL (e.g., `http://localhost:9000`) is responsive. **Wait an additional 5 seconds** for JS bundles and assets to fully load.

   **Otherwise** (standard app): Run the dev server command from project discovery **in the background** (append `&`), capture the process ID, and extract the local URL from the server output. **Poll the URL every 2 seconds, up to 120 seconds**, until it returns a successful response. **After the server responds, wait an additional 5 seconds** for JS bundles and assets to fully load.

   **Do not call any `playwright-mcp` tool until all checks pass.**

2. **Capture screenshots** - For each element in manifest, use `playwright-mcp`:
   - Navigate to page or trigger component (follow any **Setup** steps in the manifest entry)
   - Wait for content to stabilize
   - Take screenshot → save to `$WORK_DIR/baseline/<name>.png`

3. **Verify** - Compare the list of `.png` files in `$WORK_DIR/baseline/` against manifest entries. Every manifest entry must have a corresponding screenshot.

4. **Stop application**: `kill $DEV_PID` and `podman stop migration-console okd-console 2>/dev/null || docker stop migration-console okd-console 2>/dev/null || true`

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

1. **Start application and wait** - **The application MUST be running and fully responsive before any `playwright-mcp` interaction.**

   **If `IS_CONSOLE_PLUGIN=true`** (multi-stage startup): Use the console dev command from `$WORK_DIR/console-dev-setup.json`. **Run the dev command as a foreground script** (do NOT append `&` — it manages its own background processes). The script performs these steps internally, in strict order:
   - **Step A**: Starts the webpack dev server on port 9001 in the background
   - **Step B**: Polls port 9001 until it responds (**HTTP 404 / curl exit code 22 is acceptable**)
   - **Step C**: Starts the console bridge on port 9000 in the background — **this MUST NOT happen before Step B succeeds**
   - **Step D**: Polls port 9000 until it responds with HTTP 200

   After the script completes, verify the console dev URL (e.g., `http://localhost:9000`) is responsive. **Wait an additional 5 seconds** for JS bundles and assets.

   **Otherwise** (standard app): Run the dev server command from project discovery **in the background** (append `&`), capture the process ID, and extract the URL from output. **Poll the URL every 2 seconds, up to 120 seconds.** After the server responds, **wait an additional 5 seconds** for JS bundles and assets.

   **Do not call any `playwright-mcp` tool until all checks pass.**
2. **Capture screenshots** - For each element in manifest, use `playwright-mcp`:
   - Navigate to page or trigger component
   - Wait for content to stabilize
   - Take screenshot → save to `$WORK_DIR/post-migration-N/<name>.png` (N = fix round, starting at 0)
3. **Stop application**

**Step 2: Compare**

Compare `$WORK_DIR/baseline/` against `$WORK_DIR/post-migration-N/`.

**Ground rules for comparison:**
- **The baseline screenshot is the source of truth.** The post-migration screenshot must look identical to it.
- **Do not rationalize differences.** If something looks different, it IS different. Do not explain away a difference as "expected due to the migration" or "acceptable styling variation." You have no context about what the migration should change visually — your only job is to detect what changed.
- **Report every visible difference**, no matter how small. A slightly different shade, a font weight change — all are differences and must be reported.
- **When in doubt, report it.** False positives are acceptable. Missed differences are not.
- **You MUST visually inspect every screenshot yourself.** Do not write scripts, use PIL, ImageMagick, or any automated pixel-diffing tool as a substitute for looking at the images. You are a multimodal model — read the image files directly and describe what you see.
- **Compare regions independently.** A page has distinct regions (masthead, sidebar, content area, modals). Each region may have different styling. Check each region's colors against the baseline — do not summarize the page as "all dark" or "all light."

**Efficiency:**
- **Load each image only once.** When comparing a pair of screenshots, read both files in a single step or back-to-back, then perform all analysis from those reads. Do not re-load the same image file multiple times for different analysis passes.
- **Batch your reads.** If your runtime supports parallel tool calls, load multiple image pairs in parallel rather than sequentially.

**Subpixel / Anti-aliasing Noise:**
Differences where fewer than 0.5% of pixels differ **and** the maximum per-channel difference is ≤ 15 are almost certainly font anti-aliasing artifacts from the rendering engine. **Do not report these as issues.** Instead, list them in a separate "Identical (within anti-aliasing tolerance)" section at the end of the report — no checkboxes, just a note. This avoids generating dozens of unfixable items that waste time in the fix phase.

First, for each manifest entry verify that **both** baseline and post-migration screenshots exist. If a post-migration screenshot is missing, report it as `❌ Major`.

For each element in manifest where both screenshots exist:
1. **Load both images** (baseline and post-migration)
1a. **Verify page content matches the manifest description.** If the post-migration screenshot shows wrong content (e.g., a 404 page instead of the expected page, empty state when data was expected), report as `❌ Major`.
2. **Describe baseline in detail**: Inventory every visible element — sections, components, text labels, icons, colors, borders, shadows, spacing, alignment, font sizes, background colors, divider lines, badge counts, hover states, scroll positions
3. **Describe post-migration in detail**: Same inventory, independently — do not copy from the baseline description
4. **Diff the two descriptions item by item**: Walk through every element you inventoried and compare. For each, explicitly state whether it is the same or different.

**Scan for these specific difference categories:**

| Category | What to look for |
|----------|-----------------|
| Layout | Position shifts, size changes, reflow, element reordering |
| Spacing | Padding, margins, gaps between elements (even 1-2px) |
| Colors | Background, text, borders, shadows, hover states, opacity |
| Typography | Font family, size, weight, line-height, letter-spacing |
| Borders & dividers | Thickness, style (solid/dashed), color, radius |
| Icons | Different icon, different size, different color, missing |
| Components | Missing, added, or replaced components |
| Text content | Changed labels, truncation, wrapping differences |
| Alignment | Horizontal/vertical alignment shifts |
| Visibility | Elements present in one but hidden/absent in the other |

**You MUST explicitly address EVERY category above for each element.** State "no difference" or describe the difference. Do not skip any.

- List ALL differences found — one bullet per difference, with specific detail (e.g., "Card header padding changed from ~16px to ~12px", not "spacing changed")
- Classify each difference: ⚠️ Minor (styling/spacing/color, does not break functionality) / ❌ Major (missing elements, broken layout, functional breakage)

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

**Ground rules for fixing:**
- **The baseline screenshot is the source of truth.** The goal is to make post-migration screenshots look identical to baseline. Do not decide that a difference is "acceptable" or "expected."
- **Do not rationalize differences.** If the baseline shows X and the current screenshot shows Y, that is a difference to fix — regardless of whether the migration "should" have changed it.
- **Never dismiss the baseline as wrong or anomalous.** The baseline was captured from the working pre-migration application. If the baseline shows light content with a dark sidebar, that is the correct state to match.
- **Compare regions independently.** A page has distinct regions (masthead, sidebar, content area, modals). If the baseline sidebar is dark but the content area is light, the fix must reproduce that exact combination — not make everything uniformly dark or light.
- **Verify fixes against baseline, not against your expectations.** After making a fix, compare the new screenshot to the baseline screenshot — not to what you think it should look like.

Read `$WORK_DIR/status.md` to understand what migration issues have been fixed so far. This helps identify root causes of visual regressions.

**Start the dev server once** and keep it running for the entire fix process:

**If `IS_CONSOLE_PLUGIN=true`** (multi-stage startup): Use the console dev command from `$WORK_DIR/console-dev-setup.json`. **Run the dev command as a foreground script** (do NOT append `&` — it manages its own background processes). The script performs these steps internally, in strict order:
   - **Step A**: Starts the webpack dev server on port 9001 in the background
   - **Step B**: Polls port 9001 until it responds (**HTTP 404 / curl exit code 22 is acceptable**)
   - **Step C**: Starts the console bridge on port 9000 in the background — **this MUST NOT happen before Step B succeeds**
   - **Step D**: Polls port 9000 until it responds with HTTP 200

After the script completes, verify the console dev URL (e.g., `http://localhost:9000`) is responsive. **Wait an additional 5 seconds** for JS bundles and assets.

**Otherwise** (standard app): Start the dev server command from project discovery **in the background** (append `&`) and capture the process ID. **Poll the URL every 2 seconds, up to 120 seconds.** After the server responds, **wait an additional 5 seconds** for JS bundles and assets.

**Do not call any `playwright-mcp` tool until both checks pass.**

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

3. **Stop the dev server** after all pages have been processed: `kill $DEV_PID` and `podman stop migration-console okd-console 2>/dev/null || docker stop migration-console okd-console 2>/dev/null || true`

**Fix ALL issues (major AND minor) before completing migration.** Do not dismiss minor issues as acceptable.

Increment N and go back to step 1.

### Completion Checklist

- [ ] Visual comparison done
- [ ] ALL visual issues fixed (all checkboxes in report are `[x]`)
- [ ] Migration comments removed
