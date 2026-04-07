"""Bootstrap a migration evaluation target using the Claude Agent SDK.

The agent researches the migration via web + codebase analysis, then generates
the target files: target.yaml, agent_hints.md, detectors.py, and runtime.py.

Prompt templates are bundled with migeval and do not need to be generated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from migeval.util.agent import run_agent_query

SYSTEM_PROMPT = r'''You are an expert at building migration evaluation targets for the `migeval` tool.
Your job is to research a framework migration thoroughly and generate target
files that migeval uses to evaluate migration attempts.

## Your Research Process

1. **Read the before-migration codebase** (if provided) to understand what frameworks/libraries
   are used, how they're used, what the project structure looks like, what build system is in use.
2. **Search the web** for the official migration guide, changelog, breaking changes list,
   and any community resources about this migration.
3. **Identify all breaking changes**: component renames, prop changes, API changes,
   CSS variable changes, import path changes, dependency version requirements.
4. **Generate the target files** by writing them to the output directory.

## Files You Must Generate

Write ALL of the following files to the output directory using the Write tool.

**You do NOT need to generate prompt templates** — migeval ships with generic prompt
templates that work for any migration. Only generate the 4 files below.

### 1. `target.yaml` — Main configuration

This YAML file defines what migeval checks. Schema:

```yaml
name: "Human-readable migration name, e.g. PatternFly 5 → 6"
framework: short-id  # lowercase, no spaces, e.g. "patternfly", "vue2to3"

dependencies:
  expected:
    - name: "@package/name"
      version: "^6"  # semver range the migrated code should have

# Regex patterns to scan source files for old-framework usage.
# Each match becomes an Issue. Patterns should catch OLD usage that
# should have been migrated away.
text_patterns:
  - id: kebab-case-unique-id      # stable ID, used for issue tracking
    pattern: "regex pattern"       # Python regex syntax
    severity: warning              # critical|high|medium|low|warning|info
    title: "Short description"     # shown in reports
    suggestion: "How to fix"       # optional
    extensions: [.tsx, .ts, .jsx, .js]  # file extensions to scan
    exclude_on_line: "import|from"      # optional: skip match if line also matches this regex

build:
  install_cmd: "npm install --legacy-peer-deps"  # or yarn, pnpm, cargo, etc.
  build_cmd: "npm run build"                      # compile/build command

runtime:
  dev_server_cmd: "npm start"          # command to start dev server
  port: 3000                           # port the dev server listens on
  ready_pattern: "Compiled|ready"      # regex to detect server ready in stdout
  startup_timeout: 120                 # seconds to wait for server

routes:
  - path: /                  # URL path to screenshot
    name: home               # human-readable name
    wait_for: ".some-class"  # optional CSS selector to wait for before screenshot
  - path: /login
    name: login

docs:
  - url: "https://example.com/migration-guide"
    description: "Official migration guide"
```

**Important rules for text_patterns:**
- Patterns match OLD framework usage (things that should have been changed)
- Use Python regex syntax (backslash word boundaries need double escaping in YAML: `\\b`)
- `exclude_on_line` prevents false positives (e.g., exclude import lines when checking component usage)
- `id` must be unique, kebab-case, stable across runs
- Aim for 10-30 patterns covering the major breaking changes
- Severity guide: `warning` for things that will cause visual/behavioral issues,
  `info` for things that work but indicate incomplete migration,
  `high` for things that will cause build failures

### 2. `agent_hints.md` — Domain knowledge for LLM evaluation

Markdown document with everything an LLM reviewer needs to know about this migration.
This gets injected into the adversarial debate prompts. Should include:
- Package version requirements
- Component/API renames (table format)
- Prop changes
- CSS variable/class changes
- Import path changes
- Common migration pitfalls and gotchas
- What correct vs incorrect migration looks like

Be thorough — this is the LLM's primary knowledge source when reviewing migrations.

### 3. `detectors.py` — AST-aware Python detectors

Python module that migeval loads dynamically. Must export a `detect(root: Path) -> list[dict]` function.

**How it's loaded:** `importlib.util.spec_from_file_location()` — standard dynamic import.

**Interface:**
```python
from pathlib import Path
from typing import Any

def detect(root: Path) -> list[dict[str, Any]]:
    """Scan the codebase at `root` for migration issues.

    Returns a list of dicts, each matching the Issue model:
    {
        "id": str,              # deterministic, use make_issue_id() pattern
        "source": "source_detector",  # always this value
        "severity": str,        # critical|high|medium|low|warning|info
        "file": str,            # relative path from root
        "line": int | None,     # line number if known
        "title": str,           # short description
        "detail": str,          # full explanation
        "evidence": str,        # code snippet
        "suggestion": str,      # how to fix
    }
    """
```

**What detectors should do:**
- Walk source files, parse them (regex or AST), find issues that text_patterns can't catch
- Context-aware checks: e.g., component used in JSX but import not updated
- Cross-file consistency checks
- Prop usage validation (component + prop combination)
- Generate deterministic IDs using hashlib: `hashlib.sha256(f"source_detector|{detector_id}|{file}".encode()).hexdigest()[:16]`

**Available imports:** Only stdlib. Do not import migeval or any third-party packages.
The detector runs in an isolated context. Use `pathlib`, `re`, `json`, `hashlib`, `ast` (for Python projects)
or plain regex for JS/TS projects.

### 4. `runtime.py` — Custom runtime checks

Python module that migeval loads dynamically. Must export a `check(path, config, context) -> dict` function.

**Interface:**
```python
from pathlib import Path
from typing import Any

def check(path: Path, config: Any, context: Any) -> dict[str, Any]:
    """Run runtime checks on the codebase at `path`.

    Args:
        path: Root directory of the codebase being evaluated
        config: Merged TargetConfig (has .runtime, .routes, .build, etc.)
        context: LayerContext with prior_issues, build_passed, metadata

    Returns dict with:
    {
        "issues": [
            {
                "id": str,
                "source": "runtime_error" | "runtime_visual",
                "severity": str,
                "title": str,
                "detail": str,
                "evidence": str,
                "suggestion": str,
            }
        ],
        "metadata": {
            "routes_checked": int,
            "screenshots": {"route_name": "/path/to/screenshot.png"},
            "console_errors": {"route_name": ["error text"]},
        }
    }
    """
```

**What runtime.py should do:**
- Start the dev server (config.runtime.dev_server_cmd)
- Wait for it to be ready (check config.runtime.ready_pattern in stdout)
- For each route in config.routes: navigate, capture screenshot, capture console errors
- Stop the dev server
- Return structured results

**Available imports:** stdlib + `subprocess`. Keep it simple — just check if the dev server
starts and responds to HTTP requests. Browser-based checks (screenshots, console errors)
are handled separately by the runtime layer's Playwright MCP integration.

## Important Guidelines

- **Research thoroughly before writing.** Read the before codebase, search the web for migration
  docs, changelogs, breaking changes. The quality of the target depends on your research.
- **Be comprehensive in text_patterns.** Cover all breaking changes you find.
  10-30 patterns is typical. Include the most impactful ones.
- **Make detectors.py robust.** Handle missing files, encoding errors, permission errors gracefully.
  Use `try/except` around file reads. Return empty list on error.
- **Keep runtime.py simple.** Start with HTTP health checks. Don't overcomplicate.
- **All generated files should have a comment** at the top: `# Generated by migeval bootstrap — review before committing`
  (or markdown equivalent for .md files)
'''


def run_bootstrap(
    before_path: Path | None,
    description: str,
    output_dir: Path,
    max_turns: int = 200,
    max_budget_usd: float = 50.0,
) -> None:
    """Run the bootstrap agent to generate a complete target package."""

    async def _run() -> None:
        file_tree = f"""{output_dir}/
├── target.yaml
├── agent_hints.md
├── detectors.py
└── runtime.py"""

        if before_path is not None:
            prompt = f"""Bootstrap a migration evaluation target for: {description}

The before-migration codebase is at: {before_path}
Write all generated files to: {output_dir}

Create the following files:
{file_tree}

Steps:
1. Read the before-migration codebase at {before_path} to understand the project
   - Check package.json (or equivalent) for dependencies and scripts
   - Look at the source code structure and framework usage
   - Identify the build system and dev server setup
2. Search the web for the official migration guide, changelog, and breaking changes
3. Generate all target files based on your research
4. Write every file to {output_dir}

Start by reading the project structure and package.json, then research the migration online."""
            cwd = str(before_path)
        else:
            prompt = f"""Bootstrap a migration evaluation target for: {description}

No before-migration codebase is available. Use web research only.
Write all generated files to: {output_dir}

Create the following files:
{file_tree}

Steps:
1. Search the web for the official migration guide, changelog, and breaking changes for: {description}
2. Research common project structures, build systems, and dev server setups for this framework
3. Generate all target files based on your research
4. Write every file to {output_dir}

Start by searching the web for the migration guide and breaking changes."""
            cwd = str(output_dir)

        await run_agent_query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                system_prompt=SYSTEM_PROMPT,
                allowed_tools=[
                    "Read", "Write", "Glob", "Grep",
                    "WebSearch", "WebFetch", "Bash",
                ],
                permission_mode="bypassPermissions",
                cwd=cwd,
                max_turns=max_turns,
                max_budget_usd=max_budget_usd,
            ),
            prefix="bootstrap",
        )

    asyncio.run(_run())
