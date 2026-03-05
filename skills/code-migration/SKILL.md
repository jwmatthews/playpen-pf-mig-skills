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

   WRONG — will hang forever:
   ```bash
   cd <project_path> && npm start
   ```

   RIGHT — backgrounds the process:
   ```bash
   cd <project_path> && npm start &
   NPM_PID=$!
   ```

   You MUST:
   1. **Always run them in the background** (append `&`) and capture the PID (`$!`). **Never run them in the foreground.**
   2. **Poll for readiness** after starting: check the server URL with `curl` every 2 seconds for up to 120 seconds. Only proceed after the server responds. **For the webpack dev server (port 9001), an HTTP 404 response (`Cannot GET /`, curl exit code 22) is expected and acceptable** — it means the server is running but the console bridge has not connected yet. Do NOT require HTTP 200 from the webpack dev server.
   3. **Do not run the dev command here to test it.** Just construct and save it. The subagents (`visual-captures`, `visual-fix`) will handle execution with proper background management and readiness polling.
   4. **When running multi-line scripts via `bash -c`, every command must be separated by semicolons (`;`) or newlines (`\n`).** Pasting a multi-line script into a single `bash -c` argument without semicolons will silently fail — commands after the first line become positional parameters and are never executed. **Write the dev command as a shell script file** (`$WORK_DIR/start-dev.sh`) and execute it with `bash $WORK_DIR/start-dev.sh`, rather than passing a long command string to `bash -c`.

   - If script exists: **Before using it, read the script contents to determine how it starts the console bridge.** Check whether the script runs `podman run` or `docker run` with or without the `-d` (detach) flag:
     - If the script runs the container **without `-d`** (foreground/blocking), the script itself will never exit. **You must run the script in the background** with `&` and capture its PID.
     - If the script runs the container **with `-d`** (detached mode), the container starts in the background and the script exits on its own. **Do not background the script** with `&` — let it run to completion so any startup errors are reported.
     - **If you cannot determine the behavior from reading the script, default to running it in the background** with `&` to avoid hanging the session.

     Dev command starts the webpack dev server in the background FIRST, polls until it is listening, then runs the console script with
     `BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT` and `BRIDGE_K8S_AUTH_BEARER_TOKEN` set from credentials.

     Example (blocking script — run with `&`):
     ```bash
     # 1. Start webpack dev server in background (long-running, never exits)
     cd <project_path> && npm start &
     NPM_PID=$!
     # 2. Poll until webpack dev server is ready on port 9001 (up to 120s)
     # The server returns HTTP 404 ("Cannot GET /") until the console bridge connects — this is expected.
     # Accept both exit code 0 (HTTP 200) and exit code 22 (HTTP 404) as "server is ready".
     for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:9001 2>/dev/null; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 22 ] && break; sleep 2; done
     # 3. Start console bridge in background (script runs container in foreground, so script itself blocks)
     BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT=<api_server> BRIDGE_K8S_AUTH_BEARER_TOKEN=<token> bash ./ci/start-console.sh &
     # 4. Poll until console bridge is ready on port 9000 (up to 120s)
     for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:9000 2>/dev/null && break; sleep 2; done
     ```

     Example (detached script — script runs `podman run -d` and exits):
     ```bash
     # 1. Start webpack dev server in background (long-running, never exits)
     cd <project_path> && npm start &
     NPM_PID=$!
     # 2. Poll until webpack dev server is ready on port 9001 (up to 120s)
     for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:9001 2>/dev/null; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 22 ] && break; sleep 2; done
     # 3. Run console bridge script (it starts the container with -d and exits on its own)
     BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT=<api_server> BRIDGE_K8S_AUTH_BEARER_TOKEN=<token> bash ./ci/start-console.sh
     # 4. Poll until console bridge is ready on port 9000 (up to 120s)
     for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:9000 2>/dev/null && break; sleep 2; done
     ```
   - If no script: dev command starts the webpack dev server in the background FIRST, polls until it is listening, then runs a generic podman console bridge:
     ```bash
     # 1. Start webpack dev server in background (long-running, never exits)
     cd <project_path> && npm start &
     NPM_PID=$!
     # 2. Poll until webpack dev server is ready on port 9001 (up to 120s)
     # The server returns HTTP 404 ("Cannot GET /") until the console bridge connects — this is expected.
     # Accept both exit code 0 (HTTP 200) and exit code 22 (HTTP 404) as "server is ready".
     for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:9001 2>/dev/null; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 22 ] && break; sleep 2; done
     # 3. Start console bridge in background (also long-running)
     podman run --rm --name=migration-console --network=host \
       -e BRIDGE_USER_AUTH=disabled -e BRIDGE_K8S_MODE=off-cluster \
       -e BRIDGE_K8S_MODE_OFF_CLUSTER_ENDPOINT=<api_server> \
       -e BRIDGE_K8S_MODE_OFF_CLUSTER_SKIP_VERIFY_TLS=true \
       -e BRIDGE_K8S_AUTH=bearer-token -e BRIDGE_K8S_AUTH_BEARER_TOKEN=<token> \
       -e BRIDGE_PLUGINS=<plugin_name>=http://localhost:9001 \
       -e BRIDGE_LISTEN=http://0.0.0.0:9000 \
       quay.io/openshift/origin-console:latest &
     # 4. Poll until console bridge is ready on port 9000 (up to 120s)
     for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:9000 2>/dev/null && break; sleep 2; done
     ```
   - **Both servers must be running**: webpack dev server on port 9001 (serves plugin JS) and console bridge on port 9000 (provides the HTML shell that loads the plugin)
   - Console dev URL is `http://localhost:9000`
   - **Save the console dev command as a shell script file** at `$WORK_DIR/start-dev.sh` (not as a JSON string). Multi-line shell scripts with backgrounded processes, loops, and conditionals break when passed as `bash -c` arguments. Also save the URL to `$WORK_DIR/console-dev-setup.json` with a reference to the script path.

6. **Check target technology specific guidance**: Look for a target-specific file in `targets/`. Match by lowercased target name without version numbers (e.g., "PatternFly 6" → `patternfly.md`, "Spring Boot 3.x" → `spring-boot.md`). **Follow ALL pre-migration steps in the target file sequentially — each step must complete before the next one starts. Do not proceed to Phase 2 until all pre-migration steps are complete.**

---

## Phase 2: Fix Loop

### First Round Only

Run initial analysis to create the fix plan:

1. Run Kantra: `kantra analyze --input <project> --output $WORK_DIR/round-1/kantra --overwrite <FLAGS>`
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
- **NEVER run dev servers in the foreground** — `npm start`, `webpack serve`, `npm run dev`, and similar dev server commands start an HTTP server that runs indefinitely and **never exits on their own**. Running them without `&` WILL hang your session indefinitely. Always: (1) run in background with `&` and capture PID (`$!`), (2) poll the server URL with `curl` every 2 seconds for up to 120 seconds until it responds, (3) only then proceed to the next step. **When polling the webpack dev server (port 9001), accept HTTP 404 (curl exit code 22) as ready** — the server returns `Cannot GET /` until the console bridge connects, which is normal.
- **The entire dev command must run as a single bash `-c` script, not as separate commands.** When constructing the dev command, write it as one multi-line shell script. Do NOT split it into separate sequential shell invocations — backgrounded processes (`&`) and their PIDs (`$!`) are only valid within the same shell session.
