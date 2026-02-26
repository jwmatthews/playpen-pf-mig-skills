---
name: code-migration
description: Migrate applications between technologies using kantra static analysis and automated fixes. Use when migrating Java, Node.js, Python, Go, or .NET applications. Keywords: kantra, migration, upgrade, modernize.
---

# Code Migration

Migrate applications by identifying issues from multiple sources, fixing them systematically, and validating the result.

## Issue Sources

Collect issues from ALL of these sources during analysis.

| Source | Examples |
|--------|----------|
| Kantra analysis | Deprecated APIs, breaking changes, migration patterns |
| Build errors | Compilation failures, type errors, missing deps |
| Lint errors | Style violations, unused imports |
| Test failures | Broken tests from API changes |
| Target docs | Breaking changes Kantra doesn't detect (check `targets/<target>.md`) |

Kantra is a static source code analysis tool that uses rules to identify migration issues in the source code.

---

## Phase 1: Discovery

1. **Explore project**: Delegate to `project-explorer` subagent with the path to the project. Get build command, dev server command, test commands, lint command.

2. **Detect OpenShift Console plugin**: Check whether the project is an OpenShift Console dynamic plugin. Look for **all** of these indicators:
   - `@openshift-console/dynamic-plugin-sdk` in `package.json` dependencies or devDependencies
   - A `console-extensions.json` file in the project root
   - A `ConsolePlugin` resource in any YAML/JSON file under the project

   If **any** indicator is present, mark the project as a console plugin. Record this in `$WORK_DIR/status.md` under a `## Project Type` heading once the workspace is created.

3. **Build Kantra command**: Ask user:
   - Use custom rules? (If yes, get path)
   - Enable default rulesets?

   Delegate to `kantra-command-builder` subagent with the path to the project, the migration goal (target technology), custom rules path (if provided), and whether to enable default rulesets.

   It returns flags; you add `--input` and `--output`.

4. **Create workspace**: Create temp directory *outside* the project:
   ```bash
   WORK_DIR=$(mktemp -d -t migration-$(date +%m_%d_%y_%H))
   ```
   **All subagent delegations below use this directory as the work directory.** All migration artifacts — Kantra output, status files, screenshots, manifests, and reports — must go inside `$WORK_DIR`. Never use the project directory as the work directory.

5. **Check target technology specific guidance**: Read `targets/<target>.md` if it exists. Follow pre-migration steps before Phase 2.

---

## Phase 2: Fix Loop

### First Round Only

Run initial analysis to create the fix plan:

1. Run Kantra: `kantra analyze --input <project> --output $WORK_DIR/round-1/kantra <FLAGS>`
2. Parse Kantra output using the helper script:
   - Overview: `python3 scripts/kantra_output_helper.py analyze $WORK_DIR/round-1/kantra/output.yaml`
   - File details: `python3 scripts/kantra_output_helper.py file $WORK_DIR/round-1/kantra/output.yaml <file>`
3. Run build, lint, unit tests (delegate to `test-runner` subagent with the test command from project discovery, specifically ask for unit tests)
4. Collect ALL issues from ALL sources (see Issue Sources table)
5. Create `$WORK_DIR/status.md` using the template below

### Fix Loop Template

Create `$WORK_DIR/status.md`:

```markdown
# Migration Status

## Groups

- [ ] Group 1: [Name] - [Brief description]
- [ ] Group 2: [Name] - [Brief description]
- [ ] Group 3: [Name] - [Brief description]

## Group Details

### Group 1: [Name]
**Why grouped**: [Related issues, same subsystem, etc.]
**Issues**:
- [Issue from Kantra/build/lint/tests]
- [Issue from Kantra/build/lint/tests]
**Files**: [file1.ts, file2.ts]

### Group 2: [Name]
...

## Round Log

(Append after each round)
```

### Each Round

```
Round Checklist:
- [ ] Pick next incomplete group
- [ ] Apply fixes for that group
- [ ] Run Kantra + build + lint + unit tests
- [ ] Mark group complete in status.md
- [ ] Add new issues to plan if any appeared
```

1. **Pick**: Select first incomplete group from status.md
2. **Fix**: Apply all fixes for that group
3. **Validate**: Run Kantra, build, lint, unit tests (delegate to `test-runner` subagent with the test command, specifically ask for unit tests)
4. **Update**: Mark the group's checkbox as `[x]` in status.md and log the round. **Always keep status.md up to date** — it is the source of truth for migration progress.

Append to status.md:
```markdown
### Round N: [Group Name]
- Fixed: [count] issues
- New issues: [count or "none"]
- Build: PASS/FAIL
- Tests: PASS/FAIL/NONE
```

### Exit Check

After each round, check:

| Condition | Done? |
|-----------|-------|
| All groups complete | ☐ |
| Kantra: 0 issues | ☐ |
| Build: passes | ☐ |
| Unit tests: pass | ☐ |

- **Any unchecked** → Continue loop (next group)
- **All checked** → Proceed to Phase 3

### If Stuck

If the same issue appears 3+ rounds, delegate to `issue-analyzer` subagent with the workspace directory path (`$WORK_DIR`).

---

## Phase 3: Final Validation

Run E2E/behavioral tests and complete target-specific validation.

### E2E Testing

1. Delegate to `test-runner` subagent with the test command from project discovery, specifically ask for e2e / integration tests
2. If tests FAIL → Fix issues, re-run
3. If tests PASS → Continue to target-specific validation

### Console Plugin Cluster Validation

**Only perform this section if the project was detected as an OpenShift Console dynamic plugin in Phase 1 step 2.**

Console dynamic plugins must be tested inside an OpenShift Console to verify they load, register their extensions, and render correctly.

1. **Provision cluster**: Delegate to `kind-cluster` subagent with the desired cluster name. It returns JSON with `cluster_name`, `api_server`, `console_url`, `token`, `kubeconfig_path`, `ca_cert_path`, and `context_name`. Save the returned JSON to `$WORK_DIR/cluster-credentials.json`.

2. **Build plugin image**: Build the plugin container image using the project's build tooling (typically `npm run build` followed by a container build). Tag it as `localhost/console-plugin:latest`.

3. **Load image into kind**: `kind load docker-image localhost/console-plugin:latest --name <cluster_name>`

4. **Deploy plugin to cluster**: Create a Deployment, Service, and `ConsolePlugin` CR in the cluster. Use the project's existing deployment manifests if available, otherwise create minimal resources serving the plugin assets on port 9001.

5. **Enable the plugin**: Patch the console to load the plugin. If the `consoles.operator.openshift.io` CRD does not exist (vanilla Kubernetes), skip — the plugin loads via the `ConsolePlugin` CR.

6. **Verify**: Confirm the plugin appears in the console at the `console_url`. Check the console pod logs for plugin loading errors.

Log the result in `$WORK_DIR/status.md`:
```markdown
### Cluster Validation
- Console plugin deployed: YES/NO
- Plugin loaded in console: YES/NO
- Console URL: <url>
```

### Target-Specific Validation

**Follow all post-migration steps in `targets/<target>.md`. These steps are mandatory — do not skip them.** The migration is not complete until all post-migration validation passes.

### Exit Criteria

All must be checked:

- [ ] Kantra: 0 issues
- [ ] Build: passes
- [ ] Unit tests: pass
- [ ] E2E tests: pass
- [ ] Target-specific validation complete
- [ ] Console plugin loads in cluster (if console plugin project)

Update status.md:
```markdown
## Complete

- Total rounds: N
- Build: PASS
- Unit tests: PASS
- E2E tests: PASS
- Target validation: PASS
- Console plugin validation: PASS/SKIP
```

---

## Phase 4: Report

Before generating the report, write the final `## Action Required` section to status.md. This must reflect the **end state** of the migration, including visual fixes.

1. Read `$WORK_DIR/visual-diff-report.md` — check for any unchecked (`[ ]`) issues that remain after the visual fix loop
2. Read `$WORK_DIR/visual-fixes.md` — understand what visual issues were fixed and how
3. Remove any `visual_review` items from Action Required that were resolved by the visual-fix agent (i.e., the corresponding issues are now `[x]` in the diff report)
4. Add any **new** items discovered during visual fixing that need user attention (e.g., unfixable visual differences)

Append the final `## Action Required` section to status.md listing **every item the user should still review**. Use bullet format with type prefix:

```markdown
## Action Required

- **Unresolved Issue**: [description] → [recommendation]
- **False Positive**: [description] → [recommendation]
- **Visual Review** (page: [name]): [description] → [recommendation]
- **Manual Intervention**: [description] → [recommendation]
```

If nothing requires review:

```markdown
## Action Required

None
```

Then delegate to `report-generator` subagent with the workspace directory path, source technology, target technology, and project path.

Tell the user the path to the generated `report.html`.

---

## Guidelines

- **One group per round** for clear feedback
- **Follow planned order** - foundation before dependent changes
- **Verify each fix** - don't break existing features
- **Document unfixable issues** after 2+ failed approaches
- **Use all issue sources** - Kantra is just one input
