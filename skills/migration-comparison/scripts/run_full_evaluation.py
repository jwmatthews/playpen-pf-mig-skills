#!/usr/bin/env python3
"""
End-to-end evaluation orchestrator.

Runs the full evaluation pipeline:
1. Deterministic pipeline (enumerate -> diff -> categorize -> score) per attempt
2. LLM adversarial review (optional, via --llm-review)
3. Compose evaluation results + scorecard
4. Generate HTML report

Usage:
    python3 scripts/run_full_evaluation.py \
      --golden /path/to/golden-truth \
      --attempt ai-agent=/path/to/ai-output \
      --attempt codemods=/path/to/codemods-output \
      --output-dir /tmp/eval-run-001 \
      --target patternfly \
      --llm-review
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_script(cmd: list[str], description: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """Run a pipeline script and handle failures."""
    print(f"\n{'─'*60}")
    print(f"  {description}")
    print(f"{'─'*60}")
    result = subprocess.run(cmd, capture_output=False, text=True, timeout=timeout)
    if result.returncode != 0:
        print(f"\nError: {description} failed (exit code {result.returncode})", file=sys.stderr)
        sys.exit(1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run full evaluation pipeline: deterministic + LLM review + report"
    )
    parser.add_argument(
        "--golden",
        required=True,
        help="Path to the golden truth directory",
    )
    parser.add_argument(
        "--before-migration",
        default=None,
        help="Path to the source codebase before any migration was applied",
    )
    parser.add_argument(
        "--attempt",
        action="append",
        required=True,
        dest="attempts",
        help="Named attempt in 'name=/path' format (can specify multiple)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write all evaluation artifacts",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Migration target for pattern scoring (e.g., 'patternfly')",
    )
    parser.add_argument(
        "--llm-review",
        action="store_true",
        help="Enable LLM adversarial review (requires claude CLI)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum LLM debate rounds (default: 3)",
    )
    parser.add_argument(
        "--no-gumtree",
        action="store_true",
        help="Skip GumTree AST diffing",
    )

    args = parser.parse_args()

    scripts_dir = Path(__file__).parent.resolve()
    golden_dir = Path(args.golden).resolve()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Validate golden dir
    if not golden_dir.is_dir():
        print(f"Error: Golden truth directory not found: {golden_dir}", file=sys.stderr)
        sys.exit(1)

    # Validate before-migration dir (optional)
    before_dir: Path | None = None
    if args.before_migration:
        before_dir = Path(args.before_migration).resolve()
        if not before_dir.is_dir():
            print(f"Error: Before-migration directory not found: {before_dir}", file=sys.stderr)
            sys.exit(1)

    # Validate attempts
    attempt_args: list[str] = []
    for attempt_str in args.attempts:
        if "=" not in attempt_str:
            print(f"Error: --attempt must be 'name=/path', got: {attempt_str}", file=sys.stderr)
            sys.exit(1)
        name, path = attempt_str.split("=", 1)
        attempt_path = Path(path.strip()).resolve()
        if not attempt_path.is_dir():
            print(f"Error: Attempt directory not found: {attempt_path}", file=sys.stderr)
            sys.exit(1)
        attempt_args.append(f"{name.strip()}={attempt_path}")

    print(f"{'='*60}")
    print(f"  Migration Evaluation Pipeline")
    print(f"{'='*60}")
    print(f"  Golden truth: {golden_dir}")
    if before_dir:
        print(f"  Before migration: {before_dir}")
    for a in attempt_args:
        name, path = a.split("=", 1)
        print(f"  Attempt '{name}': {path}")
    print(f"  Output: {output_dir}")
    print(f"  Target: {args.target or '(generic)'}")
    print(f"  LLM review: {'enabled' if args.llm_review else 'disabled'}")

    # Step 1: Deterministic pipeline
    eval_cmd = [
        sys.executable, str(scripts_dir / "run_evaluation.py"),
        "--golden", str(golden_dir),
        "--output-dir", str(output_dir),
    ]
    if before_dir:
        eval_cmd.extend(["--before-migration", str(before_dir)])
    for a in attempt_args:
        eval_cmd.extend(["--attempt", a])
    if args.target:
        eval_cmd.extend(["--target", args.target])
    if args.no_gumtree:
        eval_cmd.append("--no-gumtree")

    run_script(eval_cmd, "Step 1: Deterministic Pipeline")

    # Step 2: LLM adversarial review (optional)
    if args.llm_review:
        llm_cmd = [
            sys.executable, str(scripts_dir / "run_llm_review.py"),
            "--output-dir", str(output_dir),
            "--golden", str(golden_dir),
            "--max-rounds", str(args.max_rounds),
        ]
        if before_dir:
            llm_cmd.extend(["--before-migration", str(before_dir)])
        for a in attempt_args:
            llm_cmd.extend(["--attempt", a])
        if args.target:
            llm_cmd.extend(["--target", args.target])

        run_script(llm_cmd, "Step 2: LLM Adversarial Review", timeout=1800)

    # Step 3: Compose evaluation results + scorecard
    compose_cmd = [
        sys.executable, str(scripts_dir / "compose_evaluation.py"),
        "--output-dir", str(output_dir),
        "--golden", str(golden_dir),
    ]
    if before_dir:
        compose_cmd.extend(["--before-migration", str(before_dir)])
    for a in attempt_args:
        compose_cmd.extend(["--attempt", a])
    if args.target:
        compose_cmd.extend(["--target", args.target])

    run_script(compose_cmd, "Step 3: Compose Results & Scorecard")

    # Step 4: Generate HTML report
    report_cmd = [
        sys.executable, str(scripts_dir / "generate_evaluation_report.py"),
        str(output_dir),
    ]
    run_script(report_cmd, "Step 4: Generate HTML Report")

    # Step 5: Generate Markdown report
    md_report_cmd = [
        sys.executable, str(scripts_dir / "generate_markdown_report.py"),
        str(output_dir),
    ]
    run_script(md_report_cmd, "Step 5: Generate Markdown Report")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Evaluation Complete")
    print(f"{'='*60}")
    print(f"\n  Artifacts:")
    print(f"    HTML Report: {output_dir / 'evaluation-report.html'}")
    print(f"    MD Report:   {output_dir / 'evaluation-report.md'}")
    print(f"    Results:     {output_dir / 'evaluation-results.json'}")
    print(f"    Scorecard:   {output_dir / 'scorecard.json'}")
    if args.llm_review:
        print(f"    LLM Review:  {output_dir / 'llm-assessment.json'}")
    print(f"\n  Open the report: xdg-open {output_dir / 'evaluation-report.html'}")
    print(str(output_dir))


if __name__ == "__main__":
    main()
