# V2 Migration Evaluation Tool — Plan

## Context

V1 required a "golden truth" (human-authored migration) to grade against. Problems:
- The quipucords golden truth isn't great
- Requiring one limits where the tool can be used
- Comparing to golden answers "does it match the human?" not "is it correct?"

V2 drops the golden truth. Evaluates on **absolute quality**: does it build? are there old-framework patterns remaining? what violations exist? Compares N migration attempts against the **before** (pre-migration) state and against each other.

Driven by Shawn: "The eval framework should OUTPUT specific things that are breaking."

## Architecture

```
comparison-tool/v2/
├── pyproject.toml
├── README.md
│
├── migeval/                          # The library (pip installable)
│   ├── __init__.py
│   ├── py.typed                      # PEP 561 marker
│   ├── cli.py                        # Click CLI: evaluate, compare subcommands
│   ├── config.py                     # Load project YAML + target config (typed)
│   ├── models.py                     # Pydantic v2: Issue, LayerResult, EvaluationRun
│   ├── orchestrator.py               # Run layers on before + each attempt → compare → report
│   ├── workspace.py                  # Git ref checkout via worktrees, temp dirs
│   │
│   ├── layers/                       # Evaluation layers (4 layers)
│   │   ├── __init__.py
│   │   ├── base.py                   # EvaluationLayer protocol
│   │   ├── source.py                 # Text pattern scan + optional Python detectors + dep check
│   │   ├── build.py                  # Install + build, parse errors, LLM error analysis
│   │   ├── runtime.py                # Evidence capture via target's runtime checks
│   │   └── llm_review.py             # Holistic LLM review of all evidence
│   │
│   ├── comparison.py                 # Before-vs-attempt, attempt-vs-attempt
│   ├── regression.py                 # Current run vs previous run
│   │
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── json_report.py           # Structured JSON output (evaluation.json)
│   │   └── markdown_report.py       # Markdown to stdout + file
│   │
│   └── util/
│       ├── __init__.py
│       ├── llm.py                   # Shared LLM client: prompt, cache, token tracking
│       ├── playwright.py            # Playwright helpers: screenshot routes, console capture
│       ├── ast_helpers.py           # Tree-sitter helpers (from v1)
│       ├── diff.py                  # Diff pipeline (from v1)
│       ├── file_enum.py             # File enumeration (from v1)
│       └── subproc.py               # Safe subprocess with timeouts
│
└── targets/                          # Config packages (not library code)
    └── patternfly/
        ├── target.yaml               # Deps, text patterns, build/runtime config, docs URLs
        ├── detectors.py              # Optional: PF5→PF6 AST-aware detectors (loaded dynamically)
        ├── runtime.py                # Optional: custom runtime checks (loaded dynamically)
        ├── prompts/                  # LLM prompt templates as markdown
        │   ├── critic.md             # Adversarial loop: wide-net issue finder
        │   ├── challenger.md         # Adversarial loop: push back on critic
        │   ├── judge.md              # Adversarial loop: resolve disputes
        │   ├── consolidator.md       # Adversarial loop: final output
        │   ├── source_bootstrap.md   # Generate text patterns for new targets
        │   ├── build_analyze.md      # Analyze build failures
        │   └── runtime_discover.md   # Discover runtime config
        └── agent_hints.md            # Domain knowledge for LLM evaluating PF migrations
```

**Target resolution**: `--target patternfly` looks in the bundled `targets/` dir (sibling to `migeval/`, found relative to the package or repo root). `--target-dir /path/to/my-target` loads an external target from anywhere on disk. Python files (detectors.py, runtime.py) are loaded dynamically via `importlib.util.spec_from_file_location()` — standard plugin loading. `TargetConfig` carries the resolved target directory path so layers can locate these files.

### Key Design Principles

#### 1. Four Evaluation Layers

Each layer is fundamentally different in what it does:

```
     LLM Review      ← AI reviews all evidence holistically
      Runtime         ← runs the app, captures behavior
       Build          ← compiles it, captures errors
      Source          ← scans code: regex + optional AST detectors
```

#### 2. Layers vs Targets

**Layers** (`migeval/layers/`) = generic evaluation machinery. "How to evaluate."
- source.py scans files for patterns and checks deps — gets patterns from target config, optionally loads detectors from target's detectors.py
- build.py runs build commands — gets commands from target/project config
- runtime.py captures runtime evidence — calls target's runtime.py if it exists, or uses generic Playwright with routes from config
- llm_review.py sends evidence to LLM — loads prompt templates from target's prompts/

**Targets** (`targets/<name>/` or external via `--target-dir`) = framework-specific config packages. "What to evaluate."
- target.yaml: text patterns, expected deps, build/runtime config, routes, docs URLs
- detectors.py: **optional** — AST-aware detector functions (loaded dynamically via importlib)
- runtime.py: **optional** — custom runtime checks using migeval's shared utilities
- prompts/*.md: LLM prompt templates with {{variable}} placeholders
- agent_hints.md: natural language domain knowledge for the LLM

Targets live **outside** the migeval package — they're config, not library code. Built-in targets ship in `targets/` alongside the package. External targets can live anywhere and are loaded via `--target-dir`. **Minimum viable target = target.yaml + agent_hints.md — no Python required.** Python (detectors.py, runtime.py) is optional for targets that need deterministic, repeatable, token-free checks.

#### 3. LLM as Cross-Cutting Assistant

The LLM isn't just the top review layer — it assists every layer:

**Source layer LLM assist** — bootstrap text patterns:
- First run with a new target: no text_patterns in target.yaml? LLM analyzes the before-migration code + migration context and generates patterns.
- Saves generated patterns to target.yaml (or a cache file). User reviews, edits, commits.
- Subsequent runs use the cached patterns deterministically — no LLM needed.
- Prompt template: `prompts/source_bootstrap.md`

**Build layer LLM assist** — discover commands + analyze failures:
- No build config? LLM inspects package.json/Makefile/Cargo.toml to figure out install_cmd + build_cmd.
- When build fails: LLM categorizes errors, identifies root causes, distinguishes migration-caused errors from pre-existing issues.
- Prompt template: `prompts/build_analyze.md`

**Runtime layer LLM assist** — discover runtime config:
- No runtime config? LLM figures out the dev server command, port, and which routes to test from the project structure.
- After evidence capture: LLM interprets screenshots and console errors (handled by the LLM review layer, not the runtime layer itself).
- Prompt template: `prompts/runtime_discover.md`

**LLM Review layer** — adversarial debate loop:
- Receives ALL evidence from all layers (issues, build errors, screenshots, console output).
- Runs 4-role adversarial loop: Critic → Challenger → Judge → Consolidator.
- Each role catches what the previous missed or over-reported.
- Prompt templates: `prompts/critic.md`, `challenger.md`, `judge.md`, `consolidator.md`

**Key principle**: first run is LLM-assisted exploration (generates config). Subsequent runs are deterministic replay (uses cached config). The LLM is a one-time setup cost, not a per-run cost.

Generated configs are saved to `--output-dir` (e.g., `eval-output/.migeval-cache/`) and clearly marked as LLM-generated. Users review and commit them into their target directory for subsequent deterministic runs.

#### 4. Typed Python

- `mypy --strict` enforced
- All function signatures fully typed
- `Protocol` for the layer interface (structural typing)
- Pydantic v2 enforces model types
- `py.typed` marker (PEP 561)
- `Literal` types for enums (LayerName, IssueSource, Severity)

## CLI Interface

```bash
migeval evaluate \
  --before /path/to/v5 \
  --attempt fa=/path/to/attempt1 \
  --attempt codemods=/path/to/attempt2 \
  --output-dir ./eval-output \
  --target patternfly \
  --config project.yaml \
  --layers source,build,runtime,llm \
  --violations fa=kantra-output.yaml \
  --previous-run ./prev-eval/evaluation.json

# Git ref support
migeval evaluate \
  --before main~1 \
  --attempt feat/pf6 \
  --repo /path/to/repo \
  --target patternfly

# CI mode
migeval evaluate \
  --before /path/to/v5 \
  --attempt fa=/path/to/attempt \
  --target patternfly \
  --layers source,build \
  --fail-on build-fail

# External target from anywhere on disk
migeval evaluate \
  --before /path/to/v5 \
  --attempt migrated=/path/to/attempt \
  --target-dir ./my-custom-target/

# Regression: compare two runs of the same setup over time
migeval compare \
  ./eval-run-041/evaluation.json \
  ./eval-run-042/evaluation.json
```

**Comparison model**: All attempts must be passed to a single `migeval evaluate` call. Within-run comparisons (before-vs-attempt, attempt-vs-attempt) are computed automatically. `migeval compare` is for **regression tracking only** — comparing two runs of the same setup over time (e.g., "did our migration tool improve between Tuesday and Thursday?"). It matches attempts by name across the two evaluation.json files.

**`--violations`**: Maps an attempt name to a violations file (kantra output.yaml, semver report.json). Uses same `name=path` pattern as `--attempt`. Also auto-discovers `<attempt-path>/output.yaml` if present — explicit flag overrides auto-discovery.

**Output**: Clear structured logging to stderr while running. Markdown report to stdout (pipeable). JSON + markdown files written to `--output-dir`.

**`--layers`**: Defaults to all available (`source,build,runtime,llm`). Each layer skips gracefully if prerequisites aren't met, so the default is safe.

**`--llm-max-rounds`**: Maximum Critic ↔ Challenger rounds in the adversarial loop (default: 3). Loop stops earlier if issues converge.

**Exit codes**: 0 = ok, 1 = infra error, 2 = `--fail-on` triggered

## Evaluation Layers

**Runs on before + attempts**: Source, Build, and Runtime all run on **both** the before-migration baseline and each attempt. This establishes baselines so comparisons show real deltas (e.g., "before had 142 pattern matches, attempt has 28 → 114 fixed"). Each codebase builds and runs with its own deps — before uses PF5, attempts use whatever they migrated to. Only **LLM Review** runs on attempts only (it reviews migration quality, not baselines).

### 1. Source (always runs, no external deps)

Scans source files for issues. Multiple capabilities within one layer:

- **Text pattern scan**: regex-match source files against patterns from target.yaml. Simple string matching, no context awareness. Run on before and each attempt — delta shows what was fixed.
- **Detectors** (optional): if the target provides `detectors.py`, load it dynamically and run detector functions. AST-aware, context-aware (understands imports, JSX structure, prop relationships). Deterministic, no token cost.
- **Dependency check**: parse package.json (or equivalent), check against expected versions in target.yaml. Before will show 0/4 correct (expected), attempts should show improvement.
- **Violation parse**: consume kantra output.yaml or semver report.json if provided via `--violations`. Violations are passed to the layer through `LayerContext.violations` (populated by the orchestrator from `--violations` CLI flag).

**LLM assist**: if no text_patterns in target.yaml, ask LLM to generate them from the migration context. Cache the result.

### 2. Build (needs the build toolchain)
- Run `install_cmd` then `build_cmd` (both from target/project config).
- Parse error output — handle common formats (tsc, webpack, vite, go build, make).
- On before: establishes that the code built successfully pre-migration. On attempts: shows whether migration broke the build.
- Graceful skip if toolchain not available.

**LLM assist**: if no build config, ask LLM to discover commands from project files. When build fails, ask LLM to categorize errors and identify root causes.

### 3. Runtime (needs build pass + appropriate tooling)
- If the target provides `runtime.py`: call its `check()` function, which uses shared utilities (Playwright, kubectl, etc.) as needed.
- If no `runtime.py` but target has `runtime:` config: use generic Playwright capture (screenshot routes, capture console errors).
- If neither: skip gracefully.
- On before: captures visual baseline screenshots + console state. On attempts: captures post-migration state for visual diff comparison.
- **Evidence capture only** — runtime layer collects data, doesn't interpret it. LLM review layer interprets.
- Graceful skip if build failed or required tools missing.

**LLM assist**: if no runtime config, ask LLM to discover dev server command, port, and routes from project structure.

### 4. LLM Review (attempts only, needs LLM access, optional)
- Runs on **attempts only** — reviews migration quality, not the pre-migration baseline.
- Receives all evidence from other layers (issues, build errors, screenshots, console errors) plus before-vs-attempt delta and before screenshots for visual comparison context.
- Prompt templates in `targets/<name>/prompts/`.
- Graceful skip if no LLM available.

**Adversarial debate loop** — the core mechanism for LLM review. Four roles:

1. **Critic**: Reviews all evidence and identifies migration issues. Casts a wide net — may include false positives. Produces a list of candidate issues with severity, evidence, and reasoning.
2. **Challenger**: Receives the Critic's issues and pushes back. For each issue: is this actually a problem? Is the evidence sufficient? Could this be a false positive? Is the severity correct? Produces rebuttals or confirmations for each issue.
3. **Judge**: Receives the full debate history and rules on any issues still disputed after the loop. Produces a filtered list of validated issues with final severity.
4. **Consolidator**: Takes the Judge's validated issues and produces the final output — deduplicates against issues already found by other layers, assigns stable IDs, formats as `Issue` objects.

**The loop** (Critic ↔ Challenger):
- **Round 1**: Critic finds issues → Challenger rebuts
- **Round 2**: Critic defends findings, refines, or concedes → Challenger rebuts again
- **Round N**: Continue until **convergence** or **max rounds** (default: 3)
- **Convergence**: The loop stops when the set of issues stabilizes — no new issues added, no issues dropped, no severity changes between rounds. Detected by diffing the Critic's issue list between rounds.
- **Then**: Judge rules on anything still disputed → Consolidator finalizes

**Max rounds** is configurable (CLI flag `--llm-max-rounds`, default 3). In practice, most debates converge in 2 rounds. The cap prevents runaway token spend.

Each role gets its own prompt template (`targets/<name>/prompts/critic.md`, `challenger.md`, `judge.md`, `consolidator.md`) so they can be tuned per-target. Round 2+ prompts include the full debate history from prior rounds so each role has context.

**Graceful degradation**: each layer independent. Report shows what ran and what was skipped (with reason). If build fails, runtime auto-skips. If required tools missing, runtime skips. If no LLM, LLM-assist features and LLM review skip. Source always runs.

## Data Models

```python
# --- Literal types ---
LayerName = Literal["source", "build", "runtime", "llm"]
IssueSource = Literal[
    "source_match", "source_detector", "source_dependency", "source_violation",
    "build_error", "runtime_error", "runtime_visual", "llm_review",
]
Severity = Literal["critical", "high", "medium", "low", "warning", "info"]

# --- Sub-models (used in config and layer protocol) ---

class TextPattern(BaseModel):
    id: str
    pattern: str               # regex
    severity: Severity
    title: str
    suggestion: str = ""
    extensions: list[str] = []
    exclude_on_line: str = ""  # regex — skip match if line also matches this

class DependencyConfig(BaseModel):
    expected: list[dict[str, str]]  # [{name, version}]

class BuildConfig(BaseModel):
    install_cmd: str
    build_cmd: str

class RuntimeConfig(BaseModel):
    dev_server_cmd: str
    port: int
    ready_pattern: str = ""    # regex to detect server ready in stdout
    startup_timeout: int = 120

class RouteConfig(BaseModel):
    path: str
    name: str
    wait_for: str = ""         # optional CSS selector to wait for before screenshot

class DocRef(BaseModel):
    url: str
    description: str = ""

class LayerContext(BaseModel):
    """Evidence accumulated from prior layers, passed to each subsequent layer."""
    prior_issues: list["Issue"] = []
    build_passed: bool | None = None  # None = build layer hasn't run
    violations: dict[str, Any] | None = None  # from --violations, passed to source layer
    metadata: dict[str, Any] = {}     # layer-specific data (screenshots, build output)

# --- Core models ---

class Issue(BaseModel):
    id: str                    # deterministic, stable across runs (see ID scheme below)
    source: IssueSource        # source_match, source_detector, source_dependency, source_violation, build_error, runtime_error, runtime_visual, llm_review
    severity: Severity         # critical, high, medium, low, warning, info
    file: str | None
    line: int | None           # for display only, not part of ID
    title: str                 # short summary
    detail: str                # full explanation
    evidence: str = ""         # code snippet, error text, screenshot path
    suggestion: str = ""
    pattern_id: str | None = None

class LayerResult(BaseModel):
    layer: LayerName           # source, build, runtime, llm
    success: bool              # ran without infra errors
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float
    issues: list[Issue]
    metadata: dict[str, Any]   # layer-specific (build: exit_code, raw_output; runtime: screenshots)

class AttemptResult(BaseModel):
    name: str
    path: str
    git_ref: str | None
    layer_results: dict[LayerName, LayerResult]
    total_issues: int
    issues_by_severity: dict[Severity, int]
    build_passes: bool | None  # None = not checked

class AttemptDelta(BaseModel):
    attempt_a: str             # "before" or attempt name
    attempt_b: str
    resolved: list[str]        # issue IDs in a but not b
    new: list[str]             # issue IDs in b but not a
    shared: list[str]          # in both
    delta: int                 # len(new) - len(resolved)

class RegressionItem(BaseModel):
    issue_id: str
    status: Literal["new", "resolved", "changed"]
    current: Issue | None      # None if resolved
    previous: Issue | None     # None if new
    detail: str                # human-readable explanation

class EvaluationRun(BaseModel):
    version: str = "2.0"
    timestamp: str
    target: str | None
    before: AttemptResult                          # before-migration baseline
    attempts: dict[str, AttemptResult]
    before_vs_attempt: dict[str, AttemptDelta]
    attempt_vs_attempt: dict[str, AttemptDelta]    # key: "a_vs_b"
    regressions: list[RegressionItem] | None       # vs previous run

# --- Config models (loaded by config.py, not serialized to evaluation.json) ---

class TargetConfig(BaseModel):
    """Loaded from target.yaml. Carries resolved target dir path for dynamic loading."""
    target_dir: Path               # where the target lives on disk
    name: str
    framework: str
    dependencies: DependencyConfig | None = None
    text_patterns: list[TextPattern] = []
    build: BuildConfig | None = None
    runtime: RuntimeConfig | None = None
    routes: list[RouteConfig] = []
    docs: list[DocRef] = []

class ProjectConfig(BaseModel):
    """Loaded from --config YAML. Overrides TargetConfig values per-project."""
    project: dict[str, str] | None = None
    build: BuildConfig | None = None
    runtime: RuntimeConfig | None = None
    routes: list[RouteConfig] = []
    hints: str = ""
```

### Issue ID Scheme

IDs are deterministic hashes so the same issue produces the same ID across runs:
- **Source text match**: `hash("source_match", pattern_id, file)` — line excluded because it shifts between attempts
- **Source detector**: `hash("source_detector", detector_id, file)` — detector functions provide their own stable ID
- **Source dependency**: `hash("source_dependency", package_name)` — one issue per mismatched package
- **Source violation**: `hash("source_violation", rule_id, file)` — from kantra/semver output
- **Build errors**: `hash("build_error", file, error_code)` — uses tsc/webpack error code, not full message text
- **Runtime errors**: `hash("runtime_error", route, error_text_prefix)` — console error on a specific route
- **Runtime visual**: `hash("runtime_visual", route)` — one issue per route with visual evidence
- **LLM review** (non-deterministic): `hash("llm_review", title)` — best effort, regression tracking for LLM issues is approximate

Comparison operates at the type+file level: "does pattern X still appear in file Y?" Counts track improvement.

## Target Config (targets/patternfly/target.yaml)

```yaml
name: "PatternFly 5 → 6"
framework: patternfly

dependencies:
  expected:
    - name: "@patternfly/react-core"
      version: "^6"
    - name: "@patternfly/patternfly"
      version: "^6"
    - name: "@patternfly/react-icons"
      version: "^6"
    - name: "@patternfly/react-table"
      version: "^6"

# Text patterns: simple regex scans for old-framework strings.
# No context awareness — broad signals that may include false positives.
# For context-aware detection, add detectors.py instead.
text_patterns:
  - id: pf-v5-css-prefix
    pattern: "pf-v5-"
    severity: warning
    title: "PF5 CSS class prefix"
    suggestion: "Replace pf-v5- with pf-v6-"
    extensions: [.tsx, .ts, .css, .scss, .jsx, .js]
  - id: pf-v5-css-var
    pattern: "--pf-v5-"
    severity: warning
    title: "PF5 CSS variable prefix"
    extensions: [.tsx, .ts, .css, .scss]
  - id: deprecated-import
    pattern: "from ['\"]@patternfly/react-core/deprecated['\"]"
    severity: info
    title: "Import from deprecated module"
    extensions: [.tsx, .ts, .jsx, .js]
  - id: old-text-component
    pattern: "\\b(TextContent|TextList|TextListItem)\\b"
    severity: warning
    title: "Deprecated component (use Content)"
    extensions: [.tsx, .ts, .jsx, .js]
    exclude_on_line: "import|from"
  - id: old-table-composable
    pattern: "\\bTableComposable\\b"
    severity: warning
    title: "TableComposable renamed to Table"
    extensions: [.tsx, .ts, .jsx, .js]
  - id: old-spacer-value
    pattern: "\\bspacer(None|Sm|Md|Lg|Xl|2xl|3xl|4xl)\\b"
    severity: warning
    title: "Old spacer prop value (use gap*)"
    extensions: [.tsx, .ts, .jsx, .js]
  - id: old-align-value
    pattern: "['\"]align(Right|Left)['\"]"
    severity: warning
    title: "Old alignment value (use alignEnd/alignStart)"
    extensions: [.tsx, .ts, .jsx, .js]
  - id: old-global-token
    pattern: "\\bglobal_(Color|BackgroundColor|active_color|success_color|warning_color|danger_color)_"
    severity: warning
    title: "Old global_* token (use t_* in PF6)"
    extensions: [.tsx, .ts]
  - id: old-chip-component
    pattern: "\\bChip(Group)?\\b"
    severity: info
    title: "Chip/ChipGroup renamed to Label/LabelGroup"
    extensions: [.tsx, .ts, .jsx, .js]
    exclude_on_line: "import|from|deprecated"
  - id: old-empty-state-header
    pattern: "\\bEmptyStateHeader\\b|\\bEmptyStateIcon\\b"
    severity: warning
    title: "Removed EmptyState subcomponents (use titleText prop)"
    extensions: [.tsx, .ts, .jsx, .js]

build:
  install_cmd: "npm install --legacy-peer-deps"
  build_cmd: "npm run build"

runtime:
  dev_server_cmd: "npm start"
  port: 3000
  ready_pattern: "Compiled|webpack|ready|Local:"
  startup_timeout: 120

routes:
  - path: /
    name: home
    wait_for: ""              # optional CSS selector to wait for before screenshot
  - path: /login
    name: login

docs:
  - url: "https://www.patternfly.org/get-started/upgrade"
    description: "Official PF6 migration guide"
```

## Zero-Code Target Path

A new target can be created with **no Python** — just YAML and markdown, anywhere on disk:

```
my-vue-target/                # or targets/vue2to3/ in the repo
├── target.yaml               # text patterns, deps, build/runtime commands
├── prompts/
│   ├── critic.md             # Adversarial loop: wide-net issue finder
│   ├── challenger.md         # Adversarial loop: push back on critic
│   ├── judge.md              # Adversarial loop: resolve disputes
│   ├── consolidator.md       # Adversarial loop: final output
│   ├── source_bootstrap.md   # (optional) LLM pattern generation
│   ├── build_analyze.md      # (optional) LLM build error analysis
│   └── runtime_discover.md   # (optional) LLM runtime config discovery
└── agent_hints.md            # Domain knowledge for the LLM
```

Use it: `migeval evaluate --target-dir ./my-vue-target/ --before ... --attempt ...`

With LLM assist enabled, even the target.yaml contents can be bootstrapped:
1. User provides: target name + migration description ("Vue 2 → Vue 3")
2. LLM generates: text_patterns, expected deps, likely build commands
3. Tool saves generated config, marks it as `# LLM-generated — review before committing`
4. Subsequent runs use the cached config deterministically

**Spectrum of investment per target:**
- **Quickstart** (minutes): target.yaml + agent_hints.md. LLM fills gaps.
- **Solid** (hours): add hand-tuned text_patterns, build/runtime config. No LLM needed for deterministic layers.
- **Production** (days): add detectors.py for AST-aware checks, custom runtime.py for specialized checks. Full deterministic evaluation.

## Prompt Templates (targets/patternfly/prompts/)

Markdown files with `{{variable}}` placeholders:

**source_bootstrap.md** — generate text patterns:
```markdown
# Source Pattern Generation

You are helping set up migration evaluation for: {{migration_description}}

## Before-migration code sample:
{{code_sample}}

## Task
Generate a list of regex text patterns that indicate old-framework usage.
Output as YAML matching this schema:
- id: descriptive-kebab-case-id
  pattern: "regex pattern"
  severity: warning|info
  title: "Short description"
  extensions: [.tsx, .ts, ...]
```

**build_analyze.md** — analyze build failures:
```markdown
# Build Error Analysis

Migration: {{migration_description}}
Build command: {{build_cmd}}
Exit code: {{exit_code}}

## Build output:
{{build_output}}

## Task
Categorize these errors:
1. Which errors are caused by the migration?
2. Which are pre-existing?
3. What are the root causes (group related errors)?
```

**critic.md** — first pass, wide net:
```markdown
# Migration Critic

You are the Critic reviewing a {{migration_description}} migration attempt.

## Evidence from automated checks:
{{issues_summary}}

## Build output:
{{build_output}}

## Runtime evidence:
{{runtime_evidence}}

## Before vs attempt delta:
{{delta_summary}}

## Domain knowledge:
{{agent_hints}}

## Task
Identify ALL potential migration issues, including ones the automated checks missed. Cast a wide net — it's OK to include uncertain findings. For each issue provide:
- Title (short)
- Severity (critical/high/medium/low/info)
- File and approximate location
- Evidence and reasoning
- Suggestion for fix

Focus on: semantic correctness, cross-file consistency, behavioral changes, incomplete migrations, new API misuse.
```

**challenger.md** — push back on critic:
```markdown
# Migration Challenger

You are the Challenger. The Critic identified potential issues in a {{migration_description}} migration. Your job is to push back.

## Critic's findings:
{{critic_issues}}

## Original evidence:
{{issues_summary}}
{{build_output}}

## Domain knowledge:
{{agent_hints}}

## Task
For EACH of the Critic's issues, evaluate:
1. Is this actually a problem, or a false positive?
2. Is the evidence sufficient to support the claim?
3. Is the severity appropriate?
4. Could this be expected/correct behavior in the new framework?

Provide a verdict for each: AGREE, DISAGREE (with reasoning), or ADJUST (suggest different severity/framing).
```

**judge.md** — resolve disputes:
```markdown
# Migration Judge

You are the Judge. The Critic and Challenger have debated issues in a {{migration_description}} migration. Resolve their disagreements.

## Critic's findings:
{{critic_issues}}

## Challenger's rebuttals:
{{challenger_rebuttals}}

## Task
For each disputed issue, provide a final ruling:
- KEEP: issue is real, include in final report
- DROP: false positive or insufficient evidence
- MODIFY: real issue but adjust severity or framing

Provide a brief rationale for each ruling. Output only the surviving issues with final severity and framing.
```

**consolidator.md** — final output:
```markdown
# Migration Consolidator

You are the Consolidator. Produce the final list of LLM-identified migration issues.

## Judge's validated issues:
{{judge_issues}}

## Issues already found by automated checks:
{{existing_issues}}

## Task
1. Remove any issues that duplicate what automated checks already found
2. For each remaining issue, output as structured JSON:
   - title, severity, file, line (if known), detail, evidence, suggestion
3. Order by severity (critical first)
```

## Project Config (optional --config)

```yaml
project:
  name: "quipucords-ui"

# Overrides target.yaml's build: section
build:
  install_cmd: "npm install --legacy-peer-deps"
  build_cmd: "npm run build"

# Overrides target.yaml's runtime: section
runtime:
  dev_server_cmd: "npm start"
  port: 3000
  ready_pattern: "Compiled successfully"

# Overrides target.yaml's routes: section
routes:
  - path: /
    name: dashboard
    wait_for: ".pf-v6-c-page"

# Free-form hints for LLM layers
hints: |
  Standalone React frontend, no backend needed.
```

Same field names as target.yaml — project config values override target.yaml values. Lets the user customize per-project without touching target config.

## Layer Protocol

```python
# TargetConfig and ProjectConfig defined in Data Models section above.

class EvaluationLayer(Protocol):
    name: LayerName

    def can_run(
        self,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,  # check prior layer results (e.g., build_passed)
    ) -> tuple[bool, str]: ...  # (can_run, skip_reason)

    def evaluate(
        self,
        path: Path,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,  # evidence from prior layers
        llm: LlmClient | None,  # None if LLM not available
    ) -> LayerResult: ...
```

`can_run()` checks prerequisites before `evaluate()` is called. The orchestrator calls `can_run()` first, logs skip reason if false.

`llm` parameter is optional — layers work without it but can use it for bootstrap/analysis when available.

## Output

**While running**: Clear structured logging to stderr:
```
migeval v2.0 — Migration Health Evaluation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before:  /tmp/quipucords-v5
Target:  patternfly
Attempts: frontend-analyzer, codemods

[source]  ✓ before: 0/4 deps, 142 text matches, 8 detector issues (0.7s)
[source]  ✓ frontend-analyzer: 4/4 deps, 28 text matches, 4 detector issues (0.6s)
[source]  ✓ codemods: 4/4 deps, 12 text matches, 1 detector issue (0.5s)
[build]   ✓ before: PASS (0 errors) (32.0s)
[build]   ✗ frontend-analyzer: FAIL (12 errors, LLM: 3 root causes) (45.2s)
[build]   ✓ codemods: PASS (0 errors) (38.1s)
[runtime] ✓ before: 2 routes screenshotted, 0 console errors (10.1s)
[runtime] ⊘ frontend-analyzer: skipped (build failed)
[runtime] ✓ codemods: 2 routes screenshotted, 1 console error (12.5s)
[llm]     ✓ codemods: 3 additional issues found (8.2s)

━━━ Comparison: before → frontend-analyzer ━━━
Resolved: 120 issues  |  New: 15 issues  |  Net: -105

━━━ Comparison: before → codemods ━━━
Resolved: 138 issues  |  New: 3 issues  |  Net: -135

━━━ Comparison: frontend-analyzer vs codemods ━━━
codemods wins by 30 fewer issues
```

**Files written to --output-dir:**
- `evaluation.json` — full structured results (for CI, regression, `migeval compare`)
- `report.md` — markdown report (for humans, LLMs, piping)

## Reuse from V1

| V1 Source | V2 Destination | Changes |
|---|---|---|
| `v1/scripts/enumerate_files.py` | `migeval/util/file_enum.py` | Modularize |
| `v1/scripts/run_diffs.py` + `categorize_changes.py` | `migeval/util/diff.py` | Merge |
| `v1/scripts/ast_helpers.py` | `migeval/util/ast_helpers.py` | Copy |
| `v1/targets/patternfly_patterns.py` | `targets/patternfly/detectors.py` | Adapt: validate vs PF6 spec, not golden. Start with 5-8 highest-impact. |
| `v1/scripts/run_llm_review.py` | `migeval/layers/llm_review.py` | Remove golden deps, implement adversarial loop |
| `v1/scripts/llm_prompts.py` | `targets/patternfly/prompts/*.md` | Split into 4 adversarial role templates + LLM-assist templates |
| `v1/scripts/models.py` | `migeval/models.py` | Rework: issue-centric, add RegressionItem |

## Implementation Sequence

Breadth first: get all 4 layers working end-to-end, then deepen each.

### Phase 1: Foundation
1. `pyproject.toml` (deps: pydantic, click, pyyaml, mypy in dev), `py.typed`, `migeval/__init__.py`
2. `migeval/models.py` — all Pydantic models + Literal types (mypy --strict from day one)
3. `migeval/config.py` — typed YAML loading for TargetConfig + ProjectConfig
4. `targets/patternfly/target.yaml`

### Phase 2: All Layers (breadth-first)
5. `migeval/layers/base.py` — EvaluationLayer Protocol, LayerContext
6. `migeval/util/llm.py` — shared LLM client (prompt, cache, token tracking)
7. `migeval/layers/source.py` — text pattern scan + dep check + optional detectors
8. `migeval/layers/build.py` — install + build + error parsing + LLM analysis
9. `migeval/util/` — port file_enum, diff, ast_helpers, subproc from v1
10. `migeval/util/playwright.py` — Playwright helpers
11. `migeval/layers/runtime.py` — generic evidence capture + target's runtime.py
12. `targets/patternfly/prompts/*.md` — critic, challenger, judge, consolidator + LLM-assist templates
13. `targets/patternfly/agent_hints.md`
14. `migeval/layers/llm_review.py` — adversarial debate loop (Critic → Challenger → Judge → Consolidator)
15. `targets/patternfly/detectors.py` — 5-8 highest-impact from v1

### Phase 3: Comparison + CLI + Reporting
16. `migeval/comparison.py` — before-vs-attempt, attempt-vs-attempt
17. `migeval/regression.py` — vs previous run
18. `migeval/workspace.py` — git worktrees, temp dirs
19. `migeval/orchestrator.py` — wire layers → comparison → reporting
20. `migeval/cli.py` — Click CLI
21. `migeval/reporting/json_report.py`
22. `migeval/reporting/markdown_report.py`

### Phase 4: End-to-end test
23. Run against quipucords-ui with frontend-analyzer + codemods attempts
24. Verify all layers produce output, comparison works, report is useful
25. `mypy --strict` passes on entire codebase

## Verification

### Test Targets

- **Before**: `jwmatthews/quipucords-ui` at commit `3b3ce52` (PF5 state)
- **Attempt "shawn"**: `shawn-hurley/quipucords-ui` (manual/tool-assisted migration attempt based on jwmatthews)
- **Attempt "fa"** (optional): output of running `run-full-migration.sh` from `frontend-analyzer-provider` against the before state

### Verification Steps

1. `mypy --strict migeval/` passes with zero errors
2. `migeval evaluate --before jwmatthews/quipucords-ui@3b3ce52 --attempt shawn=shawn-hurley/quipucords-ui --target patternfly --layers source` — text patterns + deps work
3. Add `--layers source,build` — build errors captured, LLM categorizes failures
4. Add `--layers source,build,runtime` — screenshots captured (if Playwright available)
5. Add `--layers source,build,runtime,llm` — adversarial LLM review runs (if available)
6. Multiple `--attempt` flags (shawn + fa) — comparison works, before has its own results
7. `--previous-run` — regression tracking works
8. `--fail-on build-fail` — CI exit code works
9. Markdown report shows all layers, skipped layers with reasons, and comparisons
10. LLM-generated configs saved and clearly marked for review
