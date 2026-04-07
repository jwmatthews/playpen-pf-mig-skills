---
name: runtime-validator
description: Execute runtime validation steps against the golden truth and each migration attempt. Captures evidence (screenshots, test output, logs, HTTP responses) for use by adversarial review agents.

# For Gemini CLI, uncomment the tools section below:
# tools:
#   - run_shell_command
#   - read_file
#   - write_file
#   - list_directory
#   - search_file_content
# For Claude Code, tools may be inherited from global settings
# tools: Bash, Read, Write, Glob, Grep
---

# Runtime Validator

Execute runtime validation steps against the golden truth and each migration attempt to capture qualitative evidence that goes beyond static code analysis.

## Inputs

- **Golden truth directory path**
- **Attempt directories**: a list of `(name, path)` pairs
- **Validation config**: either user-provided validation steps or a target runtime config file (e.g., `targets/patternfly_runtime.yaml`)
- **Output directory**: where to write `runtime-validation.json`

## Validation Config

The validation config describes how to verify the migration works at runtime. It can come from:

1. **Target runtime config file** (preferred for known frameworks): YAML files in `targets/` with default commands and routes
2. **User-provided steps**: natural language from the user interview (e.g., "run `npm run dev`, screenshot the dashboard page")

A validation config contains:

- **setup_commands**: commands to install dependencies (e.g., `npm install`)
- **launch_command**: command to start the application (e.g., `npm run dev`)
- **launch_ready_signal**: string to watch for in stdout indicating the app is ready (e.g., `"ready in"`, `"Compiled successfully"`)
- **launch_timeout**: seconds to wait for ready signal (default: 120)
- **health_check**: optional URL to verify the app responds (e.g., `http://localhost:3000`)
- **test_command**: optional test suite command (e.g., `npm test -- --watchAll=false`)
- **routes_to_screenshot**: list of `{path, name}` for visual comparison (e.g., `[{path: "/", name: "home"}, {path: "/settings", name: "settings"}]`)
- **cleanup_command**: command to stop the app after validation (e.g., killing the dev server process)

## Process

### 1. Load Validation Config

If a target runtime config file path is provided, read the YAML file. Otherwise, use the user-provided steps parsed into the config fields above.

### 2. Validate Golden Truth First

Run the validation against the golden truth directory to establish the baseline:

1. `cd` into the golden truth directory
2. Run **setup_commands** (e.g., `npm install`). **If setup fails, report the error and skip runtime validation for this directory.**
3. Run **launch_command** in the background. Watch for **launch_ready_signal** in stdout/stderr.
4. If **health_check** URL is provided, poll it until it responds (up to launch_timeout).
5. If **test_command** is provided, run it and capture stdout/stderr as test evidence.
6. If **routes_to_screenshot** are provided and Chrome MCP is available, screenshot each route. Save screenshots to `$OUTPUT_DIR/screenshots/golden/<name>.png`.
7. Stop the dev server (kill the background process).

**Record all evidence** for the golden truth: test output, screenshots, health check responses, any errors.

### 3. Validate Each Attempt

For each attempt `(name, path)`, repeat the same process:

1. `cd` into the attempt directory
2. Run setup → launch → health check → tests → screenshots
3. Save screenshots to `$OUTPUT_DIR/screenshots/<attempt_name>/<name>.png`
4. Record all evidence

**Important:**
- **If setup fails for an attempt** (e.g., `npm install` errors), record the failure as evidence but continue to the next attempt. Do not abort the entire validation.
- **If the app fails to start**, record the launch failure and any error output as evidence. This is valuable signal for the adversarial review.
- **If screenshots fail** (e.g., Chrome MCP not available), skip screenshots but continue with other validation steps.

### 4. Compare Results

For each attempt, compare against the golden truth:

- **Test results**: Did the same tests pass/fail? Any new failures?
- **Screenshots**: If available, note visual differences (the adversarial agents will do the detailed visual comparison)
- **Health check**: Did the app respond? Same status code?
- **Launch behavior**: Did the app start successfully? Any warnings or errors?

### 5. Write Output

Write `$OUTPUT_DIR/runtime-validation.json` with the following structure:

```json
{
  "metadata": {
    "timestamp": "2025-01-15T10:30:00Z",
    "validation_config": {
      "launch_command": "npm run dev",
      "test_command": "npm test -- --watchAll=false",
      "routes_screenshotted": ["/", "/settings"]
    }
  },
  "golden": {
    "setup_success": true,
    "launch_success": true,
    "health_check_success": true,
    "test_results": {
      "passed": 45,
      "failed": 0,
      "skipped": 2,
      "output_summary": "Test Suites: 10 passed, 10 total"
    },
    "screenshots": ["screenshots/golden/home.png", "screenshots/golden/settings.png"],
    "errors": []
  },
  "attempts": {
    "ai-agent": {
      "setup_success": true,
      "launch_success": true,
      "health_check_success": true,
      "test_results": {
        "passed": 42,
        "failed": 3,
        "skipped": 2,
        "output_summary": "Test Suites: 8 passed, 2 failed, 10 total",
        "failures": [
          "AppHeader.test.tsx: expected MastheadLogo to be rendered",
          "Navigation.test.tsx: Cannot find module @patternfly/react-core/next"
        ]
      },
      "screenshots": ["screenshots/ai-agent/home.png", "screenshots/ai-agent/settings.png"],
      "errors": [],
      "comparison": {
        "tests_regressed": 3,
        "tests_new_failures": ["AppHeader.test.tsx", "Navigation.test.tsx"],
        "visual_differences_noted": true,
        "health_check_same": true
      }
    }
  }
}
```

## Error Handling

- **Never let a single failure abort the entire validation.** Each step (setup, launch, test, screenshot) is independent — capture what you can.
- **Record all errors as evidence.** Build failures, test failures, and launch failures are all valuable signals for the adversarial review.
- **Respect timeouts.** If an app doesn't start within `launch_timeout`, record the timeout and move on.
- **Clean up processes.** Always kill background dev server processes, even on failure. Use `kill` or the cleanup_command.

## Output

Return the path to `runtime-validation.json` and a summary:
- Number of attempts validated
- Test result comparison (pass/fail counts vs golden)
- Whether screenshots were captured
- Any validation failures encountered
