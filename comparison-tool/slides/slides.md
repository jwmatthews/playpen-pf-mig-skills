---
title: "migeval v2"
subtitle: "Migration Health Evaluation"
author: "Konveyor"
date: "April 2026"
---

# The Problem

## Evaluating migrations is hard

- We have AI agents that migrate codebases
- **How do we know if a migration actually worked?**
- Manual review doesn't scale
- "Does it compile?" is necessary but not sufficient

## Is a "golden truth" required?

- Human-authored reference migration to grade against
- Good golden truths are hard to produce
- Limits where the tool can be used
- Measures "does it match the human?" not "is it correct?"

## What we actually need

- Evaluate on **absolute quality**, not similarity
- Does it build? Are old patterns still there? What's broken?
- Compare N migration attempts against each other
- Run in CI without human intervention

---

# Proposal

## migeval v2

1. **No golden truth** --- evaluate absolute migration health
2. **Four evaluation layers** --- source, build, runtime, LLM
3. **Pluggable targets** --- new framework = YAML + markdown
4. **N-way comparison** --- before vs attempts vs each other
5. **CI-ready** --- JSON output, exit codes, regression tracking

## CLI

```bash
migeval evaluate \
  --before /path/to/v5-code \
  --attempt fa=/path/to/attempt1 \
  --attempt codemods=/path/to/attempt2 \
  --target patternfly \
  --output-dir ./eval-output
```

---

# Architecture

## Four layers

```
     LLM Review      <-- AI reviews all evidence
      Runtime        <-- runs the app, captures behavior
       Build         <-- compiles, captures errors
      Source         <-- scans code: regex + detectors
```

Each layer feeds evidence to the next.

Layers skip gracefully if prerequisites aren't met.

## Layer 1: Source

- **Text patterns**: regex scan from `target.yaml`
- **Dependency check**: right packages at right versions?
- **Detectors**: optional AST-aware checks (`detectors.py`)
- **Violations**: consume kantra / semver output

Runs on before + each attempt --- delta shows what was fixed.

## Layer 2: Build

- Runs `install_cmd` then `build_cmd`
- Parses error output (tsc, webpack, vite)
- LLM categorizes errors and identifies root causes

## Layer 3: Runtime

- Launches dev server in background
- **Playwright MCP server** via Claude Agent SDK
- Agent navigates routes, screenshots, captures console errors

```python
ClaudeAgentOptions(
    allowed_tools=["mcp__playwright__*"],
    mcp_servers={
        "playwright": {
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest"],
        },
    },
)
```

## Layer 4: LLM Review

Adversarial debate loop:

1. **Critic** --- wide net, identifies all potential issues
2. **Challenger** --- pushes back, finds false positives
3. **Judge** --- rules on disputed issues
4. **Consolidator** --- deduplicates, structured JSON

Runs Critic <-> Challenger until convergence (max N rounds).

---

# Targets System

## Layers vs Targets

| Layers (`migeval/layers/`) | Targets (`targets/<name>/`) |
|---|---|
| Generic evaluation machinery | Framework-specific config |
| "How to evaluate" | "What to evaluate" |
| Part of the library | Config packages |

## Zero-code target

```
my-target/
  target.yaml      # patterns, deps, build config
  agent_hints.md   # domain knowledge for LLM
  prompts/         # optional custom prompts
```

Use it: `migeval evaluate --target-dir ./my-target/ ...`

## Bootstrap: AI-generated targets

```bash
migeval bootstrap \
  --description "PatternFly 5 to 6" \
  --before /path/to/v5-code \
  --output-dir ./my-target
```

- Agent researches migration guide via web
- Analyzes before-codebase for patterns
- Generates `target.yaml`, `agent_hints.md`, `detectors.py`

---

# Comparison and CI

## N-way comparison

Given `before`, `attempt-A`, `attempt-B`:

- **before -> A**: resolved 120 issues, introduced 5
- **before -> B**: resolved 138 issues, introduced 3
- **A vs B**: B wins by 30 fewer issues

## CI integration

```bash
migeval evaluate \
  --before ./v5 --attempt migrated=./output \
  --target patternfly --layers source,build \
  --fail-on build-fail
```

- Exit 0: OK
- Exit 2: `--fail-on` condition met

## Regression tracking

```bash
migeval compare \
  tuesday/evaluation.json \
  thursday/evaluation.json
```

"Did our migration tool improve between runs?"

---

# Results

## PatternFly 5 -> 6: quipucords-ui

| | Before | shawn | shawn-fixed |
|---|---:|---:|---:|
| **Build** | PASS | PASS | FAIL |
| **Total issues** | 76 | 40 | 14 |
| critical | - | 9 | - |
| high | - | - | 1 |
| medium | - | 14 | 6 |
| warning | - | 11 | 4 |

## Comparisons

| | before -> shawn | before -> shawn-fixed |
|---|---:|---:|
| **Resolved** | 47 | 62 |
| **New** | 11 | 2 |
| **Net** | **-36** | **-60** |

shawn vs shawn-fixed: **shawn-fixed wins by 24 fewer issues**

## What the tool caught

- 76 source issues in `before` (PF5 patterns, wrong deps)
- `shawn-fixed` resolved 62 issues, only 2 new
- Playwright MCP captured screenshots + console errors
- LLM debate produced 7-9 targeted findings per attempt

## Key takeaways

- **No golden truth needed**
- **Bootstrapping works** --- AI-generated target found real issues
- **Adversarial debate adds value** --- catches what regex misses
- **Playwright MCP** --- real browser evidence, zero custom code
- **Pluggable** --- new migration targets in minutes
