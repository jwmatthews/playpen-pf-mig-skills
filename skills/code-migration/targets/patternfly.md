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

### 2. Capture Visual Baseline

For console plugins (detected in Phase 1): read `$WORK_DIR/console-dev-setup.json` and use the console dev command and console dev URL.

Delegate to `visual-captures` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1
- **output directory**: `$WORK_DIR/baseline`
- **project path**: path to the project source code
- **dev command**: console dev command if console plugin, otherwise dev server command from project discovery
- **dev url**: console dev URL if console plugin (e.g., `http://localhost:9000`), otherwise omit

This captures screenshots for every entry in the manifest and saves them to `$WORK_DIR/baseline/`.

### 3. Run pf-codemods

```bash
npx @patternfly/pf-codemods@latest <project_path> --v6 --fix
```

### 4. Upgrade Dependencies

Check `package.json` for all `@patternfly/*` dependencies and upgrade every one of them to `^6.x`. This includes packages like `@patternfly/react-core`, `@patternfly/react-table`, `@patternfly/react-icons`, `@patternfly/patternfly`, and any others the project uses. Then run `npm install`.

Verify build passes before continuing.

---

## During Migration

**Prefer long-term fixes.** Use new PF6 APIs. Avoid `@ts-ignore`, compatibility wrappers.

Typical order: Import paths → Component APIs → Deprecated patterns → CSS/Styling

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

**Step 2: Compare**

Delegate to `visual-compare` subagent with:
- **work directory**: the `$WORK_DIR` path created in Phase 1
- **compare directory**: `$WORK_DIR/post-migration-N`

It compares `$WORK_DIR/baseline/` against the compare directory and creates or updates `$WORK_DIR/visual-diff-report.md`.

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
