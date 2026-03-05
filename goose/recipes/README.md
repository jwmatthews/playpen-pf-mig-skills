# Goose Recipe: Code Migration

A [Goose recipe](https://block.github.io/goose/docs/guides/recipes/recipe-reference) that orchestrates code migration using [Kantra](https://github.com/konveyor/kantra) static analysis, automated fixes, and visual regression testing.

## Prerequisites

- [Goose CLI](https://github.com/block/goose) installed
- [Kantra CLI](https://github.com/konveyor/kantra) installed and available on `$PATH`
- [Playwright MCP server](https://github.com/microsoft/playwright-mcp) configured (required for visual regression testing)
- Python 3 (for helper scripts)

### Playwright MCP Setup

The visual regression subrecipes (`visual_captures`, `visual_compare`, `visual_fix`) require the [Microsoft Playwright MCP server](https://github.com/microsoft/playwright-mcp) for browser automation. Enable it via:

```bash
goose configure
```

Select the Playwright MCP extension (`@playwright/mcp@latest`) during configuration. This registers it as a `stdio` extension in your Goose profile.

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `source_tech` | Yes | - | Source technologies (e.g., `"PatternFly 5"`) |
| `target_tech` | Yes | - | Target technologies (e.g., `"PatternFly 6"`) |
| `input_path` | Yes | - | Full path to the project directory |
| `rules` | No | `""` | Comma-separated paths to custom Kantra YAML rules |
| `enable_default_rulesets` | No | `true` | Enable Kantra default rulesets |
| `workspace_dir` | No | `"<not_provided>"` | Migration workspace directory. If not provided, creates a temp directory in `/tmp` |

## Subrecipes

The recipe delegates specialized tasks to [subrecipes](https://block.github.io/goose/docs/guides/recipes/subrecipes) via the `subagent` tool:

| Subrecipe | Description |
|-----------|-------------|
| `project_explorer` | Discovers project structure, build system, test commands, lint config |
| `kantra_command_builder` | Builds the correct `kantra analyze` flags for the project |
| `test_runner` | Runs test suites and reports results |
| `issue_analyzer` | Analyzes issues that persist across 3+ fix rounds |
| `visual_captures` | Discovers UI components and captures screenshots to a given directory |
| `visual_compare` | Compares baseline and post-migration screenshots, generates checkbox-tracked report |
| `visual_fix` | Fixes unchecked visual regression issues from the diff report |

## Usage

### Interactive Mode

```bash
goose run --recipe goose/recipes/migration.yaml \
  --params source_tech="PatternFly 5" \
  --params target_tech="PatternFly 6" \
  --params input_path="/path/to/your/project"
```

With custom rules:

```bash
goose run --recipe goose/recipes/migration.yaml \
  --params source_tech="PatternFly 5" \
  --params target_tech="PatternFly 6" \
  --params input_path="/path/to/your/project" \
  --params rules="/path/to/custom-rules.yaml"
```

With a specific workspace directory:

```bash
goose run --recipe goose/recipes/migration.yaml \
  --params source_tech="PatternFly 5" \
  --params target_tech="PatternFly 6" \
  --params input_path="/path/to/your/project" \
  --params workspace_dir="/tmp/my-migration"
```

### Validate Recipe

```bash
goose recipe validate goose/recipes/migration.yaml
```

### Preview Rendered Recipe

```bash
goose run --recipe goose/recipes/migration.yaml --render-recipe \
  --params source_tech="PatternFly 5" \
  --params target_tech="PatternFly 6" \
  --params input_path="/tmp/test"
```

## Subagent Max Turns

By default, subrecipes (subagents) are limited to 25 turns. The main recipe instructs the agent to pass `settings: {max_turns: 300}` on every subagent invocation, which overrides the default.

If you need to change this globally, you can also set the `GOOSE_SUBAGENT_MAX_TURNS` environment variable:

```bash
export GOOSE_SUBAGENT_MAX_TURNS=300
```

The precedence for max turns is:
1. `settings.max_turns` in the subagent tool call (highest — set by the recipe instructions)
2. Subrecipe `settings.max_turns`
3. `GOOSE_SUBAGENT_MAX_TURNS` environment variable
4. Default (25 for subagents)

## Target-Specific Guidance

Migration targets with additional pre/post-migration steps are defined in `targets/`. Currently available:

- [`targets/patternfly.md`](targets/patternfly.md) - PatternFly 5 to 6 migration with visual regression testing

## Workflow

The recipe follows a 3-phase workflow:

1. **Discovery** - Explore project structure, build Kantra command, create workspace
2. **Fix Loop** - Iteratively fix issues in groups, validate after each round
3. **Final Validation** - Run E2E tests, execute visual regression loop (capture, compare, fix)

## Known Limitations

- Goose requires `.yaml` extension, not `.yml`
- Subrecipes run in isolation: they do not share conversation history or state with the main recipe
- Subrecipes cannot nest (a subrecipe cannot define its own subrecipes)
- The `prompt` field is required for headless/non-interactive execution
- Optional parameters must have `default` values
- All defined parameters must be referenced in templates (no orphaned definitions)
- Subrecipes are an experimental Goose feature; behavior may change in future releases

## Helper Scripts

| Script | Purpose |
|--------|---------|
| `scripts/kantra_output_helper.py` | Parses Kantra YAML output into summaries and per-file issue lists |
| `scripts/persistent_issues_analyzer.py` | Identifies issues that persist across multiple fix rounds |
