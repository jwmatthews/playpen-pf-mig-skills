# Migration Status

## Project Type
- IS_CONSOLE_PLUGIN=true
- Indicators: `@openshift-console/dynamic-plugin-sdk` in dependencies, `console-extensions.json` exists
- Plugin name: lightspeed-console-plugin

## Build System
- Build: `npm run build`
- Lint: `npm run lint-fix`
- E2E Tests: `npm run test-headless` (Cypress)
- Dev server: `npm run start` (port 9001) + `start-console.sh` (port 9000)

## Visual Baseline

**SKIPPED** — OpenShift Console bridge container (`quay.io/openshift/origin-console`) crashes under QEMU x86_64 emulation on ARM Mac (SIGSEGV in Go runtime `netpoll_epoll.go`). Tested images 4.12, 4.15, 4.18 with both podman and docker — all crash. The plugin UI only renders inside the console shell, so visual baseline screenshots cannot be captured without a working bridge.

## Test Baseline

- Total: E2E only (Cypress)
- Passing: N/A (requires running OLS backend + cluster)
- Pre-existing failures: N/A — Cypress E2E tests require a live OLS backend API and OpenShift cluster. Cannot run in this environment.

## False Positives (auto-filtered)
- None removed by filter script (0 false positives detected)

## Known False Positives / Informational (remaining 16 Kantra issues, all verified)

| Rule | Classification | Reason |
|------|---------------|--------|
| Button variant type changed (11 files) | Informational | PF6 added `stateful` variant; existing values still valid |
| sd-cf-form-form-req-wrap (4 files) | False positive | Form children (ActionGroup, FormGroup, Spinner) are valid PF6 children |
| Label color type changed (3 files) | Informational | Already fixed `gold`→`yellow`; rule notes compatible type signature change |
| IconProps removed (2 files) | Informational | Code uses `Icon` component, not `IconProps` interface directly |
| TextArea resizeOrientation type changed (2 files) | Informational | Added `none` option; existing `vertical` still works |
| sd-cf-card-card-req-expandablecontent-and-header | False positive | Card does not require CardExpandableContent or CardHeader |
| sd-cf-descriptionlist-description-not-in-group | False positive | DescriptionListDescription is correctly inside DescriptionListGroup |
| sd-cf-page-page-req-breadcrumb | False positive | Page does not require PageBreadcrumb |
| CSS logical property renames | Already fixed | Applied all suffx renames; rule persists due to broad pattern matching |
| CodeEditor signature changed | Informational | Internal readonly change, no user-facing impact |
| CodeEditorProps signature changed | Informational | Base class change (React.HTMLProps → HTMLProps), compatible |
| Card type changed | Informational | FunctionComponent → ForwardRefExoticComponent, compatible |
| Dropdown onSelect type changed | Informational | Compatible signature change |
| ExpandableSectionProps signature changed | Informational | Base class change, compatible |
| ModalProps signature changed | Informational | Already migrated to composable Modal |
| Select onSelect type changed | Informational | Compatible signature change |

## Groups

- [x] Group 1: Text/TextVariants → Content/ContentVariants - Deprecated Text component migration
- [x] Group 2: Modal Migration (ConfirmationModal) - PF5 Modal → PF6 composable Modal
- [x] Group 3: Label color `gold` → `yellow` - Label color value change
- [x] Group 4: PageSection variant `light` removed - Remove deprecated variant + utility class renames
- [x] Group 5: CSS pf-v5 → pf-v6 migration - All CSS variable and class prefix renames + logical property renames
- [x] Group 6: Test file CSS selectors - Update pf-v5 selectors in Cypress tests

## Group Details

### Group 1: Text/TextVariants → Content/ContentVariants
**Why grouped**: Text component deprecated, moved to Content in PF6
**Issues**:
- `Text` no longer exported from `@patternfly/react-core` (TS2305)
- `TextVariants` renamed to `ContentVariants`
**Files**: AttachEventsModal.tsx, AttachLogModal.tsx, AttachmentModal.tsx, NewChatModal.tsx

### Group 2: Modal Migration (ConfirmationModal)
**Why grouped**: ConfirmationModal uses PF5 Modal directly with deprecated props
**Issues**:
- Modal `title` prop → ModalHeader component
- Modal `titleIconVariant` prop → ModalHeader component
- Modal `actions` prop → ModalFooter component
- Modal `showClose` prop removed
- Modal needs composable structure (ModalHeader, ModalBody, ModalFooter)
**Files**: ConfirmationModal.tsx

### Group 3: Label color `gold` → `yellow`
**Why grouped**: PF6 removed `gold` from Label color values, replaced by `yellow`
**Issues**:
- Label color="gold" is invalid in PF6
**Files**: ResponseToolModal.tsx, ResponseTools.tsx

### Group 4: PageSection variant `light` removed
**Why grouped**: PF6 removed `light` variant from PageSection
**Issues**:
- PageSection variant="light" → remove variant (default is light in PF6)
- pf-v5-u-text-align-center → pf-v6-u-text-align-center utility classes
**Files**: GeneralPage.tsx

### Group 5: CSS pf-v5 → pf-v6 migration
**Why grouped**: All CSS variable and class renames across CSS files
**Issues**:
- 232 occurrences of `pf-v5` in pf-styles.css → all renamed
- ~60 occurrences in general-page.css → all renamed
- ~14 occurrences in popover.css → all renamed
- CSS variables: `--pf-v5-global--*` → `--pf-t--global--*` (design tokens)
- CSS class prefixes: `pf-v5-c-*` → `pf-v6-c-*`
- CSS theme classes: `pf-v5-theme-dark` → `pf-v6-theme-dark`
- CSS logical property renames: `--Left` → `--InsetInlineStart`, `--Top` → `--InsetBlockStart`, etc.
**Files**: pf-styles.css, general-page.css, popover.css

### Group 6: Test file CSS selectors
**Why grouped**: Cypress test selectors using pf-v5 class names
**Issues**:
- `.pf-v5-c-tooltip` → `.pf-v6-c-tooltip`
- `.pf-v5-c-code-editor__code` → `.pf-v6-c-code-editor__code`
**Files**: tests/tests/lightspeed-install.cy.ts

## Round Log

### Round 1: Groups 1-4 (Component Changes)
- Fixed: Text→Content (4 files), Modal composable (1 file), Label gold→yellow (2 files), PageSection variant (1 file), utility classes (1 file)
- New issues: none
- Build: PASS
- Lint: PASS

### Round 2: Group 5 (CSS Migration)
- Fixed: ~300 CSS variable/class renames across 3 CSS files + CSS logical property renames
- New issues: none
- Build: PASS
- Lint: PASS

### Round 3: Group 6 (Test Selectors)
- Fixed: 2 CSS selectors in Cypress test file
- New issues: none
- Build: PASS
- Lint: PASS

### Round 4: Final Validation (Round 3 Kantra)
- Kantra: 16 remaining issues, all classified as informational or false positives
- Build: PASS (1 warning - asset size limit)
- Lint: PASS
- Zero pf-v5 references remaining in source/test files

## Complete

- Total rounds: 4
- Build: PASS
- Lint: PASS
- Unit tests: N/A (project has no unit tests)
- E2E tests: SKIP (requires live OLS backend + OpenShift cluster)
- Visual comparison: SKIP (console bridge container crashes under ARM QEMU)
- Console plugin validation: PENDING (cluster available)

## Action Required

- **Visual Review**: Visual regression testing was skipped because the OpenShift Console bridge container (`quay.io/openshift/origin-console`) crashes under QEMU x86_64 emulation on ARM Mac. Test the plugin visually on an x86_64 machine or a real OpenShift cluster before merging.
- **E2E Test Verification**: Cypress E2E tests require a live OLS backend API and OpenShift cluster. Run `npm run test-headless` in a proper test environment to verify no regressions.
- **CSS Overrides Review**: The `pf-styles.css` file contains custom PatternFly Slider and CodeEditor CSS overrides that were mechanically renamed from `pf-v5` to `pf-v6` prefixes and design tokens. Verify these overrides still produce the intended visual result, as PF6 may have changed some underlying CSS variable values or structures.
