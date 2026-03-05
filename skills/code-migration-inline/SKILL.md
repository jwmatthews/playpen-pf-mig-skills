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

### Step 1: Explore Project Structure

Discover build system, test commands, and lint configuration.

**Find build system:**

| File Found | Build Command |
|------------|---------------|
| `package.json` | `npm run build` or `yarn build` |
| `pom.xml` | `mvn compile` or `mvn package` |
| `build.gradle` / `build.gradle.kts` | `./gradlew build` |
| `Makefile` | `make` |
| `go.mod` | `go build ./...` |
| `Cargo.toml` | `cargo build` |
| `*.csproj` / `*.sln` | `dotnet build` |

**Find test commands:**

| Test Type | How to Find |
|-----------|-------------|
| Unit tests | Check `package.json` scripts for `test`, `test:unit`; or `mvn test`, `go test ./...` |
| Integration | Look for `test:integration`, `test:e2e` scripts |
| E2E | Look for Cypress (`cypress run`), Playwright (`npx playwright test`), or similar |

**Find lint command:**

| Tool | Detection |
|------|-----------|
| ESLint | `.eslintrc*` file → `npm run lint` or `npx eslint .` |
| Prettier | `.prettierrc*` file → `npx prettier --check .` |
| Go | `golangci-lint run` |
| Python | `flake8`, `pylint`, `ruff` |

**Find dev server command:**

Look for how to run the application locally (e.g., `npm start`, `npm run dev`).

**Record findings:**

```
Build: <command>
Dev server: <command>
Lint: <command>
Unit tests: <command>
Integration tests: <command>
E2E tests: <command>
Primary language: <language>
```

### Step 2: Detect OpenShift Console Plugin

Check whether the project is an OpenShift Console dynamic plugin. Look for **all** of these indicators:
- `@openshift-console/dynamic-plugin-sdk` in `package.json` dependencies or devDependencies
- A `console-extensions.json` file in the project root
- A `ConsolePlugin` resource in any YAML/JSON file under the project

If **any** indicator is present, mark the project as a console plugin (`IS_CONSOLE_PLUGIN=true`). Record this in `$WORK_DIR/status.md` under a `## Project Type` heading once the workspace is created.

### Step 3: Build Kantra Command

Construct the Kantra analyze command flags.

**Ask user:**
- Use custom rules? (If yes, get path)
- Enable default rulesets?

**Detect provider:**

| Files Found | Provider |
|-------------|----------|
| `*.java`, `pom.xml`, `build.gradle` | `java` |
| `*.ts`, `*.tsx`, `package.json` with TS deps | `typescript` |
| `*.js`, `*.jsx`, `package.json` | `javascript` |
| `go.mod`, `*.go` | `go` |
| `*.py`, `requirements.txt`, `pyproject.toml` | `python` |
| `*.cs`, `*.csproj` | `dotnet` |

**Build flags:**

```bash
# Base flags
--provider=<detected_provider>

# If custom rules provided:
--rules=<path_to_rules>

# If default rulesets enabled (and available for target):
--target=<migration_target>
```

**You add `--input`, `--output`, and `--overwrite`:**

```bash
kantra analyze --input <project> --output $WORK_DIR/round-N/kantra --overwrite <FLAGS>
```

### Step 4: Create Workspace

```bash
WORK_DIR=$(mktemp -d -t migration-$(date +%m_%d_%y_%H))
```

### Step 5: Console Plugin Cluster Setup

**Only perform this step if `IS_CONSOLE_PLUGIN=true` (detected in Step 2).**

**5a. Prerequisites**: Verify `kubectl` and `curl` are available. If `kind` is not installed, install it:
```bash
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
[ "$ARCH" = "x86_64" ] && ARCH="amd64"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"
curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.27.0/kind-${OS}-${ARCH}"
chmod +x ./kind && mkdir -p "$HOME/.local/bin" && mv ./kind "$HOME/.local/bin/kind"
```

**5b. Create kind cluster**: Delete any existing cluster with the same name, then create one with a NodePort mapping (port 30443). Wait for the node to be Ready.

**5c. Install OLM**:
```bash
kubectl create -f https://github.com/operator-framework/operator-lifecycle-manager/releases/latest/download/crds.yaml
kubectl wait --for=condition=Established crd --all --timeout=60s
kubectl create -f https://github.com/operator-framework/operator-lifecycle-manager/releases/latest/download/olm.yaml
```
Wait for `olm-operator`, `catalog-operator`, and `packageserver` deployments to roll out. Verify the `operatorhubio-catalog` CatalogSource is READY.

**5d. Deploy OpenShift Console via OLM**: Create namespace `openshift-console`, an OperatorGroup, a ServiceAccount with cluster-admin, a `kubernetes.io/service-account-token` Secret, a ClusterServiceVersion deploying `quay.io/openshift/origin-console:latest` with `BRIDGE_K8S_MODE=off-cluster` and `BRIDGE_USER_AUTH=disabled`, and a NodePort Service on port 30443. Wait for the CSV to reach `Succeeded` and the pod to be Ready.

**5e. Verify console health**: `curl -sf -o /dev/null http://localhost:30443/health`

**5f. Collect credentials**: Extract `api_server`, `token`, `kubeconfig_path`, `ca_cert_path`, `context_name`, and `console_url`. Save to `$WORK_DIR/cluster-credentials.json`.

**5g. Determine console plugin dev command**:
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
3. **Do not run the dev command here to test it.** Just construct and save it. It will be executed later with proper background management and readiness polling.
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

### Step 6: Check Target Technology Specific Guidance

Look for a target-specific file in `targets/`. Match by lowercased target name without version numbers (e.g., "PatternFly 6" → `patternfly.md`, "Spring Boot 3.x" → `spring-boot.md`). **Follow ALL pre-migration steps in the target file sequentially — each step must complete before the next one starts. Do not proceed to Phase 2 until all pre-migration steps are complete.**

---

## Phase 2: Fix Loop

### First Round Only

Run initial analysis to create the fix plan:

1. Run Kantra: `kantra analyze --input <project> --output $WORK_DIR/round-1/kantra --overwrite <FLAGS>`
2. Parse Kantra output using the helper script:
   - Overview: `python3 scripts/kantra_output_helper.py analyze $WORK_DIR/round-1/kantra/output.yaml`
   - File details: `python3 scripts/kantra_output_helper.py file $WORK_DIR/round-1/kantra/output.yaml <file>`
3. Run build and lint commands
4. Run unit tests
5. Collect ALL issues from ALL sources (see Issue Sources table)
6. Create `$WORK_DIR/status.md` using the template below

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
3. **Validate**: Run Kantra, build, lint, unit tests
4. **Update**: Mark group done, log the round

**Run tests concisely:**
- Capture output, report only failures
- Format: `PASS: X tests, FAIL: Y tests`
- For failures, show test name and error message only

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

### If Stuck (Same Issue 3+ Rounds)

When an issue persists across 3+ rounds, analyze it:

**Run persistent issues script:**
```bash
python3 scripts/persistent_issues_analyzer.py $WORK_DIR
```

**For each persistent issue, determine:**

| Question | Check |
|----------|-------|
| False positive? | Rule too strict? Pattern actually valid? |
| Fixable? | Multiple approaches failed? Needs manual decision? |
| Blocking factor? | External deps? Domain knowledge needed? |

**Categorize:**
- **Fix**: Real issue, try different approach
- **Ignore**: False positive, document why in status.md
- **Document**: Real but needs manual intervention, add to status.md

---

## Phase 3: Final Validation

Run E2E/behavioral tests and complete target-specific validation.

### E2E Testing

1. Run E2E test command discovered in Phase 1
2. Report results concisely (pass/fail counts, failure details)
3. If tests FAIL → Fix issues, re-run
4. If tests PASS → Continue to target validation

### Console Plugin Cluster Validation

**Only perform this section if `IS_CONSOLE_PLUGIN=true` (detected in Phase 1 step 2).**

Console dynamic plugins must be tested inside an OpenShift Console to verify they load, register their extensions, and render correctly.

**1. Load cluster credentials**: Read `$WORK_DIR/cluster-credentials.json` (created in Phase 1). Verify cluster is still running by checking connectivity to the `api_server`. If not responsive, re-provision the cluster (repeat Phase 1 steps 5a-5f) and update `$WORK_DIR/cluster-credentials.json`.

**2. Build and deploy plugin**: Build the plugin container image, load it into kind, create a Deployment + Service + `ConsolePlugin` CR in the cluster. Use existing deployment manifests if available.

**3. Verify plugin**: Confirm the plugin appears in the console and check logs for loading errors.

Log the result in `$WORK_DIR/status.md`:
```markdown
### Cluster Validation
- Console plugin deployed: YES/NO
- Plugin loaded in console: YES/NO
- Console URL: <url>
```

### Target Validation

**Follow all post-migration steps in `targets/<target>.md`. These steps are mandatory — do not skip them.** The migration is not complete until all post-migration validation passes.

### Exit Criteria

All must be checked:

- [ ] Kantra: 0 issues
- [ ] Build: passes
- [ ] Unit tests: pass
- [ ] E2E tests: pass
- [ ] Target-specific validation complete
- [ ] Console plugin loads in cluster (if `IS_CONSOLE_PLUGIN=true`)

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

### 1. Read status.md

Read `$WORK_DIR/status.md` and extract:

- **Complete section**: total rounds, build/test/validation status
- **Groups**: list of groups with their completion status
- **Group Details**: for each group — name, description, files, issues
- **Round Log**: each round's fixed count, new issues, build/test results
- **Action Required section**: items the user must review (unresolved issues, false positives, visual reviews, manual interventions)

### 2. Read Kantra Assessment

Check for the latest Kantra output directory (`$WORK_DIR/round-*/kantra/output.yaml`). If a final round exists, note any residual incidents (rule, count, reason for keeping).

If no Kantra output exists, set `kantra_residual.total_incidents` to 0.

### 3. Read Visual Comparison Report

If `$WORK_DIR/visual-diff-report.md` exists, extract per-page results (page name, status, notes). Map unchecked items (`[ ]`) to `fail` status and checked items (`[x]`) to `pass`.

### 4. List Screenshot Directories

Check for `$WORK_DIR/baseline/` and `$WORK_DIR/post-migration/` directories. List filenames in each to populate the visual pages array.

If neither directory exists, set `visual.has_screenshots` to `false`.

### 5. Build report-data.json

Create `$WORK_DIR/report-data.json` using the following schema:

```json
{
  "migration": {
    "source": "string",
    "target": "string",
    "project": "string (project path)",
    "timestamp": "ISO 8601",
    "workspace": "string (workspace path)"
  },
  "summary": {
    "total_rounds": "number",
    "status": "complete|incomplete",
    "build": "PASS|FAIL",
    "unit_tests": "PASS|FAIL|NONE",
    "e2e_tests": "PASS|FAIL|NONE",
    "lint": "PASS|FAIL|NONE",
    "target_validation": "PASS|FAIL|NONE"
  },
  "action_required": [
    {
      "type": "unresolved_issue|false_positive|visual_review|manual_intervention",
      "description": "string",
      "recommendation": "string (optional)",
      "details": "string (optional)",
      "page": "string (optional, for visual_review)"
    }
  ],
  "groups": [
    {
      "name": "string",
      "status": "complete|incomplete",
      "issues_fixed": "number",
      "files": ["string"],
      "description": "string"
    }
  ],
  "rounds": [
    {
      "number": "number",
      "group": "string",
      "issues_fixed": "number",
      "new_issues": "number",
      "build": "PASS|FAIL",
      "tests": "string (e.g. '265/265' or '225/262 (37 snapshot mismatches)')"
    }
  ],
  "visual": {
    "has_screenshots": "boolean",
    "baseline_dir": "string (relative to work_dir)",
    "post_migration_dir": "string (relative to work_dir)",
    "pages": [
      {
        "name": "string",
        "baseline": "string (filename, e.g. 'login.png')",
        "post_migration": "string (filename, e.g. 'login.png')",
        "status": "pass|fail|info",
        "notes": "string"
      }
    ]
  },
  "kantra_residual": {
    "total_incidents": "number",
    "categories": [
      {
        "rule": "string",
        "count": "number",
        "reason": "string"
      }
    ]
  }
}
```

**Field population rules**:

- `migration.source` / `migration.target`: from the source and target technologies
- `migration.project`: the project path
- `migration.timestamp`: current time in ISO 8601
- `migration.workspace`: `$WORK_DIR`
- `summary`: from the Complete section of status.md
- `action_required`: from the Action Required section of status.md. Parse each bullet into type, description, and recommendation. If "None", use an empty array.
- `groups`: from Groups and Group Details sections. Mark `[x]` groups as "complete", `[ ]` as "incomplete". Count issues from Group Details. Extract files list.
- `rounds`: from Round Log entries. Parse fixed count, new issues count, build and test results.
- `visual`: from screenshot directories and visual-diff-report.md. If no screenshots exist, set `has_screenshots` to false and omit pages.
- `kantra_residual`: from the latest Kantra output. If 0 residual issues, set `total_incidents` to 0 and `categories` to empty array.

### 6. Read Visual Fixes

If `$WORK_DIR/visual-fixes.md` exists, read it to understand what visual issues were fixed and how. Use this to verify consistency of `action_required`:

- If a `visual_review` item in `action_required` refers to an issue that is now `[x]` in `visual-diff-report.md`, **remove it** from `action_required` — it was fixed.
- If `visual-diff-report.md` has unchecked (`[ ]`) issues that are **not** represented in `action_required`, **add them** as `visual_review` items.
- If `visual-fixes.md` documents fixes that contradict notes in `action_required` (e.g., an item says "not fixable" but `visual-fixes.md` shows it was fixed), update accordingly.

### 7. Verify Consistency

Before writing `report-data.json`, cross-check the data:

- `summary.status` should be `complete` only if all groups are complete, build passes, and tests pass
- `action_required` should not contain items that are contradicted by other artifacts (e.g., visual issues marked as needing review but already `[x]` in the diff report)
- `visual.pages` status values should match `visual-diff-report.md` — `[x]` → `pass`, `[ ]` → `fail`
- Every screenshot file referenced in `visual.pages` should exist in the baseline and post-migration directories

### 8. Generate HTML Report

Run:
```bash
python3 scripts/generate_migration_report.py $WORK_DIR
```

Tell the user the path to the generated `report.html`.

---

## Guidelines

- **One group per round** for clear feedback
- **Follow planned order** - foundation before dependent changes
- **Verify each fix** - don't break existing features
- **Document unfixable issues** after 2+ failed approaches
- **Use all issue sources** - Kantra is just one input
- **Report test results concisely** - counts and failures only, not full output
- **NEVER run dev servers in the foreground** — `npm start`, `webpack serve`, `npm run dev`, and similar dev server commands start an HTTP server that runs indefinitely and **never exits on their own**. Running them without `&` WILL hang your session indefinitely. Always: (1) run in background with `&` and capture PID (`$!`), (2) poll the server URL with `curl` every 2 seconds for up to 120 seconds until it responds, (3) only then proceed to the next step. **When polling the webpack dev server (port 9001), accept HTTP 404 (curl exit code 22) as ready** — the server returns `Cannot GET /` until the console bridge connects, which is normal.
- **The entire dev command must run as a single bash `-c` script, not as separate commands.** When constructing the dev command, write it as one multi-line shell script. Do NOT split it into separate sequential shell invocations — backgrounded processes (`&`) and their PIDs (`$!`) are only valid within the same shell session.
