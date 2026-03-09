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

   It returns flags; you add `--input`, `--output`, and `--overwrite`.

4. **Create workspace**: Create temp directory *outside* the project:
   ```bash
   WORK_DIR=$(mktemp -d -t migration-$(date +%m_%d_%y_%H))
   ```
   **All subagent delegations below use this directory as the work directory.** All migration artifacts — Kantra output, status files, screenshots, manifests, and reports — must go inside `$WORK_DIR`. Never use the project directory as the work directory.

5. **Console plugin cluster setup** (only if the project was detected as an OpenShift Console dynamic plugin in step 2):

   Delegate to `kind-cluster` subagent with the desired cluster name. Save the returned JSON to `$WORK_DIR/cluster-credentials.json`.

   Determine the console plugin dev command:
   - Read cluster credentials for `api_server` and `token`
   - Detect plugin name from `package.json` `name` field
   - Check for console start script (`ci/start-console.sh` or `console` script in `package.json`)

   **CRITICAL — `npm start` and webpack dev servers are long-running processes that NEVER exit on their own.**
   They start an HTTP server and keep running indefinitely to serve requests. **If you run them without `&`, your session WILL hang indefinitely and never recover.**

   You MUST construct the dev command as a **self-contained shell script** (`$WORK_DIR/start-dev.sh`) that handles cleanup, backgrounding, PID tracking, logging, and readiness polling internally. **Never run `npm start` or dev server commands directly in the shell tool** — always go through the script.

   Also create a companion **`$WORK_DIR/stop-dev.sh`** script for clean shutdown.

   **Do not run the dev command here to test it.** Just construct and save it. The subagents (`visual-captures`, `visual-fix`) will handle execution.

   - If script exists: **Before using it, read the script contents to determine how it starts the console bridge.** Check whether the script runs `podman run` or `docker run` with or without the `-d` (detach) flag:
     - If the script runs the container **without `-d`** (foreground/blocking), the script itself will never exit. **You must run the script in the background** with `&` and capture its PID.
     - If the script runs the container **with `-d`** (detached mode), the container starts in the background and the script exits on its own. **Do not background the script** with `&` — let it run to completion so any startup errors are reported.
     - **If you cannot determine the behavior from reading the script, default to running it in the background** with `&` to avoid hanging the session.

   #### start-dev.sh Template

   Every `start-dev.sh` script **MUST** follow this structure. The script handles its own backgrounding — callers run it with `bash $WORK_DIR/start-dev.sh` (no `&` needed).

   **Required elements:**
   1. **Port cleanup** — kill any leftover processes on ports 9001 and 9000 from previous failed runs
   2. **`nohup` + log redirection** — prevent shell timeout from killing the process; write output to log files
   3. **PID files** — write PIDs to `$WORK_DIR/*.pid` for clean shutdown
   4. **Readiness polling** — poll each port with `curl`, accepting exit code 22 (HTTP 404) for port 9001
   5. **Exit immediately** — the script must exit after starting and verifying servers, not block

   Example (blocking console script — run with `&`):
   ```bash
   #!/bin/bash
   WORK_DIR=<work_dir>

   # Cleanup: kill leftover processes from previous runs
   fuser -k 9001/tcp 2>/dev/null || true
   fuser -k 9000/tcp 2>/dev/null || true
   podman stop migration-console okd-console 2>/dev/null || true
   sleep 1

   # 1. Start webpack dev server in background
   cd <project_path>
   nohup npm start > "$WORK_DIR/webpack.log" 2>&1 &
   echo $! > "$WORK_DIR/webpack.pid"

   # 2. Poll until webpack dev server is ready on port 9001 (up to 120s)
   # Accept exit code 0 (HTTP 200) or 22 (HTTP 404 — "Cannot GET /") as "ready"
   for i in $(seq 1 60); do
     curl -sf -o /dev/null http://localhost:9001 2>/dev/null; rc=$?
     [ $rc -eq 0 ] || [ $rc -eq 22 ] && break
     sleep 2
   done

   # 3. Start console bridge in background (blocking script)
   BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT=<api_server> \
   BRIDGE_K8S_AUTH_BEARER_TOKEN=<token> \
   nohup bash ./ci/start-console.sh > "$WORK_DIR/bridge.log" 2>&1 &
   echo $! > "$WORK_DIR/bridge.pid"

   # 4. Poll until console bridge is ready on port 9000 (up to 120s)
   for i in $(seq 1 60); do
     curl -sf -o /dev/null http://localhost:9000 2>/dev/null && break
     sleep 2
   done
   echo "Dev servers ready"
   ```

   Example (detached console script — runs `podman run -d` and exits):
   ```bash
   #!/bin/bash
   WORK_DIR=<work_dir>

   # Cleanup: kill leftover processes from previous runs
   fuser -k 9001/tcp 2>/dev/null || true
   fuser -k 9000/tcp 2>/dev/null || true
   podman stop migration-console okd-console 2>/dev/null || true
   sleep 1

   # 1. Start webpack dev server in background
   cd <project_path>
   nohup npm start > "$WORK_DIR/webpack.log" 2>&1 &
   echo $! > "$WORK_DIR/webpack.pid"

   # 2. Poll until webpack dev server is ready on port 9001 (up to 120s)
   for i in $(seq 1 60); do
     curl -sf -o /dev/null http://localhost:9001 2>/dev/null; rc=$?
     [ $rc -eq 0 ] || [ $rc -eq 22 ] && break
     sleep 2
   done

   # 3. Run console bridge script (starts container with -d, exits on its own)
   BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT=<api_server> \
   BRIDGE_K8S_AUTH_BEARER_TOKEN=<token> \
   bash ./ci/start-console.sh > "$WORK_DIR/bridge.log" 2>&1

   # 4. Poll until console bridge is ready on port 9000 (up to 120s)
   for i in $(seq 1 60); do
     curl -sf -o /dev/null http://localhost:9000 2>/dev/null && break
     sleep 2
   done
   echo "Dev servers ready"
   ```

   - If no script: use the same structure but replace step 3 with a generic podman console bridge:
     ```bash
     # 3. Start console bridge in background (also long-running)
     podman run --rm --name=migration-console --network=host \
       -e BRIDGE_USER_AUTH=disabled -e BRIDGE_K8S_MODE=off-cluster \
       -e BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT=<api_server> \
       -e BRIDGE_K8S_MODE_OFF_CLUSTER_SKIP_VERIFY_TLS=true \
       -e BRIDGE_K8S_AUTH=bearer-token -e BRIDGE_K8S_AUTH_BEARER_TOKEN=<token> \
       -e BRIDGE_PLUGINS=<plugin_name>=http://localhost:9001 \
       -e BRIDGE_LISTEN=http://0.0.0.0:9000 \
       quay.io/openshift/origin-console:latest > "$WORK_DIR/bridge.log" 2>&1 &
     echo $! > "$WORK_DIR/bridge.pid"
     ```

   #### stop-dev.sh

   Also create `$WORK_DIR/stop-dev.sh`:
   ```bash
   #!/bin/bash
   WORK_DIR=<work_dir>
   kill $(cat "$WORK_DIR/webpack.pid" 2>/dev/null) 2>/dev/null || true
   kill $(cat "$WORK_DIR/bridge.pid" 2>/dev/null) 2>/dev/null || true
   podman stop migration-console okd-console 2>/dev/null || true
   fuser -k 9001/tcp 2>/dev/null || true
   fuser -k 9000/tcp 2>/dev/null || true
   rm -f "$WORK_DIR/webpack.pid" "$WORK_DIR/bridge.pid"
   ```

   - **Both servers must be running**: webpack dev server on port 9001 (serves plugin JS) and console bridge on port 9000 (provides the HTML shell that loads the plugin)
   - Console dev URL is `http://localhost:9000`
   - **Save the console dev command as a shell script file** at `$WORK_DIR/start-dev.sh` (not as a JSON string). Also save the URL to `$WORK_DIR/console-dev-setup.json` with a reference to the script path.

6. **Check target technology specific guidance**: Look for a target-specific file in `targets/`. Match by lowercased target name without version numbers (e.g., "PatternFly 6" → `patternfly.md`, "Spring Boot 3.x" → `spring-boot.md`). **Follow ALL pre-migration steps in the target file sequentially — each step must complete before the next one starts. Do not proceed to Phase 2 until all pre-migration steps are complete.**

---

## Phase 2: Fix Loop

### Establish Test Baseline

**Before making any code changes, run the full test suite to record pre-existing failures.** Record results in `$WORK_DIR/status.md`:

```markdown
## Test Baseline

- Total: [count]
- Passing: [count]
- Pre-existing failures:
  - [test name]: [brief reason] (NOT migration-related)
```

**Pre-existing failures do not count against the exit criteria.** The exit check is: "no NEW test failures introduced by the migration." Compare test results against this baseline, not against zero failures.

### First Round Only

Run initial analysis to create the fix plan:

1. Run Kantra — **Kantra analysis can take 5-15 minutes and will exceed the shell timeout.** Always run it in the background with `nohup` and redirect output to a log file:
   ```bash
   nohup kantra analyze --input <project> --output $WORK_DIR/round-1/kantra --overwrite <FLAGS> > $WORK_DIR/round-1/kantra-run.log 2>&1 &
   KANTRA_PID=$!
   ```
   Poll for completion: `while kill -0 $KANTRA_PID 2>/dev/null; do sleep 10; done`
   Check `$WORK_DIR/round-1/kantra/output.yaml` exists before proceeding. If Kantra failed, check `$WORK_DIR/round-1/kantra-run.log` for errors.
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
2. **Fix**: Apply all fixes for that group. **Before renaming any prop or API based on Kantra suggestions, verify the new name exists in the target framework's type definitions** (e.g., check the `.d.ts` files or run `tsc --noEmit`). Kantra rules may suggest renames that are not yet reflected in the installed version's types — applying them blindly will break the build.
3. **Validate**: Run Kantra (in background with `nohup` as described above), build, lint, unit tests (delegate to `test-runner` subagent with the test command, specifically ask for unit tests)
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
| Kantra: 0 real issues (false positives documented in status.md) | ☐ |
| Build: passes | ☐ |
| Unit tests: no new failures vs baseline | ☐ |

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

1. **Load cluster credentials**: Read `$WORK_DIR/cluster-credentials.json` (created in Phase 1). Verify cluster is still running by checking connectivity to the `api_server`. If not responsive, re-provision by delegating to `kind-cluster` subagent and update `$WORK_DIR/cluster-credentials.json`.

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

- [ ] Kantra: 0 real issues (false positives documented)
- [ ] Build: passes
- [ ] Unit tests: no new failures vs baseline
- [ ] E2E tests: pass (or no new failures vs baseline)
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
- **Never renumber, relabel, or remove groups from status.md.** Groups are numbered when the plan is created and those numbers are permanent. If a group cannot be fixed after 2+ attempts, mark it as `[!] Group N: [Name] - UNFIXABLE: [reason]` — do not delete it, reassign its number to another group, or merge it into a different group.
- **Attempt every group.** Do not skip a group because it uses deprecated-but-functional APIs. If Kantra flags it, attempt the migration to the new API. Only classify a group as unfixable if the fix breaks the build or tests after 2+ different approaches.
- **NEVER run dev servers directly in the shell tool** — `npm start`, `webpack serve`, `npm run dev`, and similar dev server commands are long-running and will hang the shell. **Always use `$WORK_DIR/start-dev.sh`** to start them and **`$WORK_DIR/stop-dev.sh`** to stop them. These scripts handle backgrounding, PID tracking, log redirection, port cleanup, and readiness polling internally. Never construct dev server commands inline.
- **Before starting dev servers, always clean up leftover processes** — run `bash $WORK_DIR/stop-dev.sh` first, or at minimum `fuser -k 9001/tcp 2>/dev/null; fuser -k 9000/tcp 2>/dev/null` to avoid `EADDRINUSE` errors from previous failed runs.
