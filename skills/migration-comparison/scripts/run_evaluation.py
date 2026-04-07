#!/usr/bin/env python3
"""
Deterministic evaluation orchestrator.

Runs the existing pipeline (enumerate → diff → categorize → score) for each
named attempt against the golden truth, producing pairwise artifacts in
sub-workspaces under the output directory.

Usage:
    python3 scripts/run_evaluation.py \
      --golden /path/to/golden \
      --attempt ai-agent=/path/to/ai-output \
      --attempt codemods=/path/to/codemods-output \
      --output-dir /tmp/eval-workspace \
      --target patternfly
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_attempt(value: str) -> tuple[str, str]:
    """Parse 'name=/path/to/dir' into (name, path)."""
    if "=" not in value:
        print(f"Error: --attempt must be in 'name=/path' format, got: {value}", file=sys.stderr)
        sys.exit(1)
    name, path = value.split("=", 1)
    name = name.strip()
    path = path.strip()
    if not name:
        print(f"Error: attempt name cannot be empty: {value}", file=sys.stderr)
        sys.exit(1)
    return name, path


def validate_directory(path: str, label: str) -> Path:
    """Validate that a directory exists and contains files."""
    p = Path(path)
    if not p.is_dir():
        print(f"Error: {label} directory not found: {path}", file=sys.stderr)
        sys.exit(1)
    return p.resolve()


def run_script(cmd: list[str], description: str) -> subprocess.CompletedProcess[str]:
    """Run a pipeline script and handle failures."""
    print(f"  → {description}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  ✗ {description} failed:", file=sys.stderr)
        if result.stderr:
            print(f"    {result.stderr.strip()}", file=sys.stderr)
        if result.stdout:
            print(f"    {result.stdout.strip()}", file=sys.stderr)
        sys.exit(1)
    # Print last line of stdout (usually the output path)
    last_line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else ""
    if last_line:
        print(f"    {last_line}")
    return result


def check_gumtree(scripts_dir: Path) -> dict[str, Any]:
    """Check GumTree availability."""
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "run_diffs.py"), "--check-gumtree"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        info: dict[str, Any] = json.loads(result.stdout.strip())
        return info
    except (json.JSONDecodeError, ValueError):
        return {"available": False, "method": "none"}


def run_pipeline_for_attempt(
    scripts_dir: Path,
    targets_dir: Path,
    golden_dir: Path,
    attempt_name: str,
    attempt_dir: Path,
    output_dir: Path,
    target: str | None,
    gumtree_info: dict[str, Any],
    before_migration_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the full deterministic pipeline for one attempt vs golden."""
    label = f"golden-vs-{attempt_name}"
    pairwise_dir = output_dir / label
    pairwise_dir.mkdir(parents=True, exist_ok=True)

    no_gumtree = not gumtree_info.get("available", False)

    print(f"\n{'='*60}")
    print(f"  Evaluating: {attempt_name}")
    print(f"  Golden: {golden_dir}")
    print(f"  Attempt: {attempt_dir}")
    print(f"  Output: {pairwise_dir}")
    print(f"{'='*60}")

    # 1. Enumerate files
    enum_cmd = [
        sys.executable, str(scripts_dir / "enumerate_files.py"),
        str(golden_dir), str(attempt_dir),
        "--label-a", "Golden Truth",
        "--label-b", attempt_name,
        "--output-dir", str(pairwise_dir),
    ]
    run_script(enum_cmd, "Enumerate files")

    # 2. Run diffs
    diff_cmd = [
        sys.executable, str(scripts_dir / "run_diffs.py"),
        "--manifest", str(pairwise_dir / "file-manifest.json"),
        "--dir-a", str(golden_dir),
        "--dir-b", str(attempt_dir),
        "--output-dir", str(pairwise_dir),
    ]
    if no_gumtree:
        diff_cmd.append("--no-gumtree")
    run_script(diff_cmd, "Run diffs")

    # 3. Categorize changes
    cat_cmd = [
        sys.executable, str(scripts_dir / "categorize_changes.py"),
        "--manifest", str(pairwise_dir / "file-manifest.json"),
        "--diff-results", str(pairwise_dir / "diff-results.json"),
        "--dir-a", str(golden_dir),
        "--dir-b", str(attempt_dir),
        "--label-a", "Golden Truth",
        "--label-b", attempt_name,
        "--output-dir", str(pairwise_dir),
    ]
    run_script(cat_cmd, "Categorize changes")

    # 4. Score migration
    score_cmd = [
        sys.executable, str(scripts_dir / "score_migration.py"),
        "--comparison-data", str(pairwise_dir / "comparison-data.json"),
        "--dir-a", str(golden_dir),
        "--dir-b", str(attempt_dir),
        "--output-dir", str(pairwise_dir),
        "--label", label,
    ]
    if target:
        score_cmd.extend(["--target", target, "--targets-dir", str(targets_dir)])
    if before_migration_dir:
        score_cmd.extend(["--before-migration", str(before_migration_dir)])
    run_script(score_cmd, "Score migration")

    # Load and return scoring results
    scoring_path = pairwise_dir / "scoring-results.json"
    if scoring_path.exists():
        with open(scoring_path, "r", encoding="utf-8") as f:
            scoring_data: dict[str, Any] = json.load(f)
            return scoring_data
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic evaluation pipeline for each attempt against golden truth"
    )
    parser.add_argument(
        "--golden",
        required=True,
        help="Path to the golden truth directory",
    )
    parser.add_argument(
        "--attempt",
        action="append",
        required=True,
        dest="attempts",
        help="Named attempt in 'name=/path' format (can be specified multiple times)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write evaluation artifacts",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Migration target for pattern scoring (e.g., 'patternfly')",
    )
    parser.add_argument(
        "--before-migration",
        default=None,
        help="Path to the source codebase before any migration was applied",
    )
    parser.add_argument(
        "--no-gumtree",
        action="store_true",
        help="Skip GumTree AST diffing",
    )

    args = parser.parse_args()

    # Resolve paths
    scripts_dir = Path(__file__).parent.resolve()
    targets_dir = scripts_dir.parent / "targets"
    golden_dir = validate_directory(args.golden, "Golden truth")
    before_migration_dir: Path | None = None
    if args.before_migration:
        before_migration_dir = validate_directory(args.before_migration, "Before-migration")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse attempts
    attempts: list[tuple[str, Path]] = []
    for attempt_str in args.attempts:
        name, path = parse_attempt(attempt_str)
        attempt_path = validate_directory(path, f"Attempt '{name}'")
        attempts.append((name, attempt_path))

    if not attempts:
        print("Error: At least one --attempt is required", file=sys.stderr)
        sys.exit(1)

    # Check GumTree
    if args.no_gumtree:
        gumtree_info: dict[str, Any] = {"available": False, "method": "none"}
        print("GumTree: disabled (--no-gumtree)")
    else:
        gumtree_info = check_gumtree(scripts_dir)
        if gumtree_info.get("available"):
            print(f"GumTree: available ({gumtree_info.get('method', 'unknown')})")
        else:
            print("GumTree: not available (text diff only)")

    print(f"\nGolden truth: {golden_dir}")
    if before_migration_dir:
        print(f"Before migration: {before_migration_dir}")
    print(f"Attempts: {', '.join(name for name, _ in attempts)}")
    if args.target:
        print(f"Target: {args.target}")

    # Run pipeline for each attempt
    all_results: dict[str, Any] = {}
    for name, attempt_path in attempts:
        scoring = run_pipeline_for_attempt(
            scripts_dir=scripts_dir,
            targets_dir=targets_dir,
            golden_dir=golden_dir,
            attempt_name=name,
            attempt_dir=attempt_path,
            output_dir=output_dir,
            target=args.target,
            gumtree_info=gumtree_info,
            before_migration_dir=before_migration_dir,
        )
        all_results[name] = scoring

    # Summary
    print(f"\n{'='*60}")
    print("  Evaluation Summary")
    print(f"{'='*60}")
    for name, scoring in all_results.items():
        score = scoring.get("score", {})
        grade = score.get("grade", "?")
        percent = score.get("overall_percent", 0)
        points = score.get("points", 0)
        pos = score.get("positive_points", 0)
        neg = score.get("negative_points", 0)
        print(f"  {name}: {grade} ({percent}%) | {points:+.1f} pts (+{pos:.1f} / {neg:.1f})")

    print(f"\nArtifacts written to: {output_dir}")
    print(str(output_dir))


if __name__ == "__main__":
    main()
