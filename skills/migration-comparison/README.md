# Migration Evaluation Tool

Answers one question: **"Is our AI migration agent providing value over just running pf-codemods?"**

Two layers:
- **Deterministic** (Python scripts): Diffs, 24 PF-specific pattern detectors, file coverage, noise analysis. Fast, reproducible, cheap.
- **LLM semantic review**: Adversarial debate loop (Critic/Challenger/Judge) using `claude -p`. Identifies high-level conceptual issues that detectors can't catch.

## Quick Start

```bash
python3 scripts/run_full_evaluation.py \
  --golden /path/to/golden-truth \
  --before-migration /path/to/pre-migration-source \
  --attempt ai-agent=/path/to/ai-output \
  --attempt codemods=/path/to/codemods-output \
  --output-dir /tmp/eval-run-001 \
  --target patternfly \
  --no-gumtree \
  --llm-review
```

Produces:
- `evaluation-report.html` -- 4-tab HTML report (Value Story, Problem Areas, Scorecard, Evidence)
- `evaluation-results.json` -- machine-readable composite results
- `scorecard.json` -- per-pattern pass/fail, designed for diffing across runs
- `llm-assessment.json` -- LLM review themes and per-file issue verdicts

## Setting Up the Quipucords Test Data

The quipucords-ui PF5-to-PF6 migration is the reference test case.

### 1. Clone the pre-migration source (before any migration)

```bash
EVAL_DIR=/tmp/qpc-eval
mkdir -p $EVAL_DIR

git clone https://github.com/quipucords/quipucords-ui.git $EVAL_DIR/base --branch main
cd $EVAL_DIR/base
git fetch origin 3b3ce52c2af3e83f16fff324c77c3b7022f8d9e3
git checkout 3b3ce52c2af3e83f16fff324c77c3b7022f8d9e3
```

This is the v2.1.0 release, the last commit before the PF6 migration PR.

### 2. Clone the golden truth (expert human migration)

```bash
cp -a $EVAL_DIR/base $EVAL_DIR/golden
cd $EVAL_DIR/golden
git fetch origin 4908c3be3cd41effbdaa508e20e50ec041f5ef4a
git checkout 4908c3be3cd41effbdaa508e20e50ec041f5ef4a
```

This is the merge commit of [PR #664](https://github.com/quipucords/quipucords-ui/pull/664) (`feat(pf6): upgrade UI to PatternFly 6`).

### 3. Clone the AI migration attempt

```bash
git clone --depth 1 https://github.com/pranavgaikwad/quipucords-ui.git $EVAL_DIR/ai-agent --branch pf5
```

This is [PR #1](https://github.com/pranavgaikwad/quipucords-ui/pull/1) (`migrate with goose + claude sonnet 4.5 + recipe`).

### 4. Generate the codemods baseline

```bash
cp -a $EVAL_DIR/base $EVAL_DIR/codemods
cd $EVAL_DIR/codemods
npm install
npx --yes @patternfly/pf-codemods --v6 --fix src/
```

This runs the official PatternFly codemods (automated transforms only, no manual fixes).

### 5. Run the full evaluation

```bash
cd /path/to/playpen-pf-mig-skills/skills/migration-comparison

python3 scripts/run_full_evaluation.py \
  --golden $EVAL_DIR/golden \
  --before-migration $EVAL_DIR/base \
  --attempt ai-agent=$EVAL_DIR/ai-agent \
  --attempt codemods=$EVAL_DIR/codemods \
  --output-dir $EVAL_DIR/results \
  --target patternfly \
  --no-gumtree \
  --llm-review
```

Open the report: `xdg-open $EVAL_DIR/results/evaluation-report.html`

## How It Works

### Architecture

```
run_full_evaluation.py (orchestrator)
  |-- run_evaluation.py (deterministic pipeline, per attempt)
  |     |-- enumerate_files.py    -> file-manifest.json
  |     |-- run_diffs.py          -> diff-results.json
  |     |-- categorize_changes.py -> comparison-data.json
  |     |-- score_migration.py    -> scoring-results.json
  |-- run_llm_review.py (adversarial LLM loop, per attempt)
  |     |-- Round N: Critic -> Challenger -> Judge (each `claude -p`)
  |     |-- Convergence check, loop until stable or max rounds
  |     |-- Consolidator: cross-file themes -> llm-assessment.json
  |-- compose_evaluation.py -> evaluation-results.json + scorecard.json
  |-- generate_evaluation_report.py -> evaluation-report.html
```

### Pattern Statuses

When `--before-migration` is provided, the scoring distinguishes:

| Status | Meaning |
|---|---|
| `correct` | Pattern migrated correctly (matches golden truth approach) |
| `incorrect` | Pattern migration attempted but wrong |
| `missing` | Pattern expected but not found in the attempt |
| `not_migrated` | File is identical to before-migration source -- attempt didn't touch it |
| `not_applicable` | Pattern not relevant to this file |

Without `--before-migration`, `not_migrated` cannot be detected and those files show as `missing` instead.

### LLM Adversarial Review (`--llm-review`)

A converging debate loop:

1. **Critic** identifies high-level migration issues (not line-level -- the deterministic layer handles that)
2. **Challenger** defends the AI's approach -- is it a valid alternative? 10 engineers would write 10 different migrations.
3. **Judge** renders verdicts with confidence scores (0.0-1.0)
4. Repeat until no disputed issues (confidence < 0.7) remain, disputed count stops decreasing, or max rounds hit
5. **Consolidator** distills verdicts into 3-7 thematic insights

Each agent is an independent `claude -p --output-format json --json-schema` call. Requires the `claude` CLI in PATH.

### Scorecard

`scorecard.json` is designed for tracking improvement across runs:

```
Tweak agent -> re-run migration -> re-run evaluation -> read scorecard
                                                      -> compare to previous scorecard
                                                      -> repeat
```

Pattern names and descriptions are human-readable so the team can understand results without PatternFly expertise.

### HTML Report Tabs

1. **Value Story** -- "AI agent provides X-point improvement over codemods." Side-by-side grades. What AI got right that codemods missed, and vice versa.
2. **Problem Areas** -- Grouped by severity. Plain-language descriptions of what went wrong and why it matters. Source-tagged (deterministic vs LLM).
3. **Scorecard** -- Pattern-by-pattern comparison table. Color-coded, designed to be screenshot-able.
4. **Evidence** -- Collapsible per-file diffs and LLM debate transcripts (Critic -> Challenger -> Judge reasoning).

## CLI Reference

```
python3 scripts/run_full_evaluation.py [OPTIONS]

Required:
  --golden PATH              Expert migration (golden truth)
  --attempt NAME=PATH        Named migration attempt (repeatable)
  --output-dir PATH          Where to write artifacts

Optional:
  --before-migration PATH    Source codebase before any migration
  --target TARGET            Target-specific patterns (e.g., 'patternfly')
  --llm-review               Enable LLM adversarial review
  --max-rounds N             Max debate rounds (default: 3)
  --no-gumtree               Skip GumTree AST diffing
```

## Running Individual Scripts

You can also run pipeline steps individually:

```bash
# Deterministic pipeline only (no LLM)
python3 scripts/run_evaluation.py \
  --golden /path/to/golden \
  --before-migration /path/to/base \
  --attempt ai-agent=/path/to/ai \
  --output-dir /tmp/eval \
  --target patternfly --no-gumtree

# LLM review only (requires deterministic results already produced)
python3 scripts/run_llm_review.py \
  --output-dir /tmp/eval \
  --golden /path/to/golden \
  --before-migration /path/to/base \
  --attempt ai-agent=/path/to/ai \
  --target patternfly --max-rounds 3

# Compose results + scorecard
python3 scripts/compose_evaluation.py \
  --output-dir /tmp/eval \
  --golden /path/to/golden \
  --before-migration /path/to/base \
  --attempt ai-agent=/path/to/ai

# Generate HTML report
python3 scripts/generate_evaluation_report.py /tmp/eval
```

## Prerequisites

- Python 3.10+
- `pydantic` (`pip install pydantic`)
- `claude` CLI in PATH (for `--llm-review`)
- Optional: `tree-sitter` + `tree-sitter-typescript` for AST analysis in pattern detectors
- Optional: GumTree for AST-level diffing (text diff works fine without it)
