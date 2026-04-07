#!/usr/bin/env python3
"""
LLM adversarial review loop using `claude -p`.

Runs a converging debate between Critic, Challenger, and Judge agents.
Each round is 3 independent `claude -p` invocations. Rounds continue until
convergence (no disputed issues) or max rounds reached.

After convergence, a Consolidator distills per-file issues into high-level themes.

Usage:
    python3 scripts/run_llm_review.py \
      --output-dir /tmp/eval-workspace \
      --golden /path/to/golden \
      --attempt ai-agent=/path/to/ai-output \
      --target patternfly \
      --max-rounds 3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def find_claude_binary() -> str:
    """Find the claude CLI binary."""
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path
    print("Error: 'claude' CLI not found in PATH", file=sys.stderr)
    sys.exit(1)


def run_claude_prompt(
    claude_bin: str,
    prompt: str,
    schema: dict[str, Any],
    output_path: Path,
    timeout: int = 300,
) -> dict[str, Any]:
    """Run a single `claude -p` call with JSON schema output.

    Pipes the prompt via stdin to avoid OS argument length limits.
    Unsets CLAUDECODE env var to allow nested invocation.
    """
    schema_str = json.dumps(schema)
    cmd = [
        claude_bin, "-p",
        "--output-format", "json",
        "--json-schema", schema_str,
    ]

    # Remove CLAUDECODE from env to avoid nested session check
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

    if result.returncode != 0:
        print(f"  Warning: claude -p returned {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"    {result.stderr[:500]}", file=sys.stderr)

    # Parse output — claude --output-format json wraps in:
    # {"result": "...", "structured_output": {...}, ...}
    # We want the structured_output (JSON schema output), not the text result.
    raw = result.stdout.strip()
    try:
        parsed = json.loads(raw)
        # Extract structured_output if present (this is the JSON schema output)
        if "structured_output" in parsed and isinstance(parsed["structured_output"], dict):
            parsed = parsed["structured_output"]
        elif "result" in parsed and isinstance(parsed["result"], str):
            try:
                parsed = json.loads(parsed["result"])
            except json.JSONDecodeError:
                pass
    except json.JSONDecodeError:
        # Try to extract JSON from the output
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except json.JSONDecodeError:
                parsed = {"error": "Failed to parse JSON output", "raw": raw[:1000]}
        else:
            parsed = {"error": "No JSON found in output", "raw": raw[:1000]}

    # Write to output path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2)

    return parsed


def prepare_review_input(
    golden_dir: Path,
    attempt_dir: Path,
    attempt_name: str,
    output_dir: Path,
    target: str | None,
    before_migration_dir: Path | None = None,
) -> dict[str, Any]:
    """Prepare review input by selecting files and assembling content."""
    # Load comparison data
    label = f"golden-vs-{attempt_name}"
    comp_path = output_dir / label / "comparison-data.json"
    scoring_path = output_dir / label / "scoring-results.json"

    if not comp_path.exists():
        print(f"Error: comparison-data.json not found at {comp_path}", file=sys.stderr)
        sys.exit(1)

    with open(comp_path, "r", encoding="utf-8") as f:
        comp_data: dict[str, Any] = json.load(f)

    scoring_data: dict[str, Any] = {}
    if scoring_path.exists():
        with open(scoring_path, "r", encoding="utf-8") as f:
            scoring_data = json.load(f)

    # Build pattern results index by file
    pattern_by_file: dict[str, list[dict[str, Any]]] = {}
    for pr in scoring_data.get("pattern_results", []):
        for detail in pr.get("details", []):
            fpath = detail.get("file", "")
            if fpath not in pattern_by_file:
                pattern_by_file[fpath] = []
            pattern_by_file[fpath].append({
                "pattern_id": pr.get("pattern_id"),
                "name": pr.get("name"),
                "status": detail.get("status"),
                "message": detail.get("message"),
            })

    # Select files for review
    files = comp_data.get("files", {})
    modified = files.get("modified", [])

    # Skip patterns
    skip_patterns = [
        r"package-lock\.json$",
        r"yarn\.lock$",
        r"pnpm-lock\.yaml$",
        r"\.snap$",
        r"__snapshots__/",
        r"node_modules/",
    ]

    review_files: list[dict[str, Any]] = []
    for file_info in modified:
        path = file_info.get("path", "")
        categories = file_info.get("categories", [])

        # Skip cosmetic-only
        if categories == ["cosmetic"]:
            continue

        # Skip excluded patterns
        if any(re.search(pat, path) for pat in skip_patterns):
            continue

        # Read file contents
        golden_file = golden_dir / path
        attempt_file = attempt_dir / path

        golden_content = ""
        attempt_content = ""
        before_content = ""
        try:
            if golden_file.exists():
                golden_content = golden_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        try:
            if attempt_file.exists():
                attempt_content = attempt_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        if before_migration_dir:
            try:
                before_file = before_migration_dir / path
                if before_file.exists():
                    before_content = before_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        file_entry: dict[str, Any] = {
            "path": path,
            "golden_content": golden_content,
            "attempt_content": attempt_content,
            "diff": file_info.get("text_diff", ""),
            "categories": categories,
            "pattern_results": pattern_by_file.get(path, []),
        }
        if before_content:
            file_entry["before_content"] = before_content
        review_files.append(file_entry)

    review_input: dict[str, Any] = {
        "attempt_name": attempt_name,
        "target": target,
        "file_count": len(review_files),
        "files": review_files,
    }

    # Write review input
    review_path = output_dir / "llm-review" / attempt_name / "review-input.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(review_input, f, indent=2)

    return review_input


def count_disputed(judge_output: dict[str, Any]) -> int:
    """Count issues with confidence < 0.7 (disputed)."""
    return sum(
        1 for v in judge_output.get("verdicts", [])
        if v.get("confidence", 0) < 0.7
    )


def run_review_loop(
    claude_bin: str,
    review_input: dict[str, Any],
    attempt_name: str,
    output_dir: Path,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Run the adversarial review loop for one attempt."""
    from llm_prompts import (
        CHALLENGER_SCHEMA,
        CONSOLIDATOR_SCHEMA,
        CRITIC_SCHEMA,
        JUDGE_SCHEMA,
        build_challenger_prompt,
        build_consolidator_prompt,
        build_critic_prompt,
        build_judge_prompt,
    )

    review_dir = output_dir / "llm-review" / attempt_name
    review_dir.mkdir(parents=True, exist_ok=True)

    # Limit file content size to keep prompts manageable
    limited_input = _limit_review_input(review_input)

    previous_judge: dict[str, Any] | None = None
    previous_disputed = float("inf")
    final_judge: dict[str, Any] = {}
    rounds_completed = 0

    for round_num in range(1, max_rounds + 1):
        print(f"\n  Round {round_num}/{max_rounds}")

        # Critic
        print(f"    Critic...")
        critic_prompt = build_critic_prompt(limited_input, previous_judge, round_num)
        critic_output = run_claude_prompt(
            claude_bin, critic_prompt, CRITIC_SCHEMA,
            review_dir / f"round-{round_num}-critic.json",
            timeout=600,
        )

        issue_count = len(critic_output.get("issues", []))
        rounds_completed = round_num
        print(f"    Critic found {issue_count} issues")

        if issue_count == 0:
            print(f"    No issues found, skipping challenger/judge")
            final_judge = {"verdicts": []}
            break

        # Challenger
        print(f"    Challenger...")
        challenger_prompt = build_challenger_prompt(limited_input, critic_output)
        challenger_output = run_claude_prompt(
            claude_bin, challenger_prompt, CHALLENGER_SCHEMA,
            review_dir / f"round-{round_num}-challenger.json",
            timeout=600,
        )

        # Judge
        print(f"    Judge...")
        judge_prompt = build_judge_prompt(limited_input, critic_output, challenger_output)
        judge_output = run_claude_prompt(
            claude_bin, judge_prompt, JUDGE_SCHEMA,
            review_dir / f"round-{round_num}-judge.json",
            timeout=600,
        )

        final_judge = judge_output

        # Check convergence
        disputed = count_disputed(judge_output)
        real_count = sum(1 for v in judge_output.get("verdicts", []) if v.get("verdict") == "real")
        print(f"    Judge: {real_count} real, {disputed} disputed (confidence < 0.7)")

        if disputed == 0:
            print(f"    Converged: no disputed issues")
            break

        if disputed >= previous_disputed:
            print(f"    Converged: disputed count not decreasing ({disputed} >= {previous_disputed})")
            break

        previous_disputed = disputed
        previous_judge = judge_output

    # Consolidator
    print(f"\n  Consolidator...")
    consolidator_prompt = build_consolidator_prompt(final_judge, attempt_name)
    consolidator_output = run_claude_prompt(
        claude_bin, consolidator_prompt, CONSOLIDATOR_SCHEMA,
        review_dir / "consolidator.json",
        timeout=300,
    )

    theme_count = len(consolidator_output.get("themes", []))
    print(f"    {theme_count} themes identified")

    return {
        "attempt_name": attempt_name,
        "rounds_completed": rounds_completed,
        "final_judge": final_judge,
        "themes": consolidator_output.get("themes", []),
    }


def _limit_review_input(review_input: dict[str, Any], max_files: int = 30, max_content: int = 4000) -> dict[str, Any]:
    """Limit review input size to keep prompts manageable."""
    limited = dict(review_input)
    files = list(review_input.get("files", []))

    # Prioritize files with pattern issues
    def file_priority(f: dict[str, Any]) -> int:
        patterns = f.get("pattern_results", [])
        has_issues = any(p.get("status") in ("incorrect", "missing") for p in patterns)
        return 0 if has_issues else 1

    files.sort(key=file_priority)
    files = files[:max_files]

    for f in files:
        for key in ("golden_content", "attempt_content"):
            if f.get(key) and len(f[key]) > max_content:
                f[key] = f[key][:max_content] + "\n... (truncated)"
        if f.get("diff") and len(f["diff"]) > max_content:
            f["diff"] = f["diff"][:max_content] + "\n... (truncated)"

    limited["files"] = files
    limited["file_count"] = len(files)
    return limited


def build_llm_assessment(
    review_results: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    """Build llm-assessment.json from review results."""
    file_assessments: list[dict[str, Any]] = []

    for result in review_results:
        attempt_name = result["attempt_name"]
        final_judge = result.get("final_judge", {})

        # Group verdicts by file (from the critic issues tracked through)
        # Load the final critic output to get file mapping
        review_dir = output_dir / "llm-review" / attempt_name
        last_round = result.get("rounds_completed", 1)

        # Find the critic output for file mapping
        critic_path = review_dir / f"round-{last_round}-critic.json"
        if not critic_path.exists():
            critic_path = review_dir / "round-1-critic.json"

        issues_by_file: dict[str, list[dict[str, Any]]] = {}
        if critic_path.exists():
            with open(critic_path, "r", encoding="utf-8") as f:
                critic_data = json.load(f)

            issue_file_map = {
                issue["id"]: issue.get("file", "unknown")
                for issue in critic_data.get("issues", [])
            }

            verdicts = {v["issue_id"]: v for v in final_judge.get("verdicts", [])}

            for issue in critic_data.get("issues", []):
                issue_id = issue["id"]
                file_path = issue.get("file", "unknown")
                verdict = verdicts.get(issue_id, {})

                if file_path not in issues_by_file:
                    issues_by_file[file_path] = []

                issues_by_file[file_path].append({
                    "id": issue_id,
                    "description": issue.get("description", ""),
                    "severity": verdict.get("final_severity", issue.get("severity", "medium")),
                    "impact_score": _severity_to_impact(verdict.get("final_severity", issue.get("severity", "medium"))),
                    "bug_finder_argument": issue.get("evidence", ""),
                    "adversary_argument": verdict.get("reasoning", ""),
                    "referee_verdict": verdict.get("verdict", "real"),
                    "referee_confidence": verdict.get("confidence", 0.5),
                })

        for file_path, issues in issues_by_file.items():
            real_issues = [i for i in issues if i.get("referee_verdict") == "real"]
            # Score: 1.0 minus impact of real issues (normalized)
            total_impact = sum(i.get("impact_score", 5) for i in real_issues)
            summary_score = max(0.0, 1.0 - (total_impact / 40.0))  # 40 = reasonable max

            file_assessments.append({
                "attempt": attempt_name,
                "file": file_path,
                "issues": issues,
                "summary_score": round(summary_score, 4),
            })

    assessment: dict[str, Any] = {
        "metadata": {
            "files_assessed": len(file_assessments),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "file_assessments": file_assessments,
        "themes": [],
    }

    # Add themes from all attempts
    for result in review_results:
        themes = result.get("themes", [])
        for theme in themes:
            theme["attempt"] = result["attempt_name"]
        assessment["themes"].extend(themes)

    # Write output
    assessment_path = output_dir / "llm-assessment.json"
    with open(assessment_path, "w", encoding="utf-8") as f:
        json.dump(assessment, f, indent=2)

    print(f"\nLLM assessment written to: {assessment_path}")
    return assessment


def _severity_to_impact(severity: str) -> int:
    """Convert severity to impact score."""
    return {"critical": 10, "high": 8, "medium": 5, "low": 2}.get(severity, 5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run LLM adversarial review loop using claude -p"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory containing pairwise artifacts",
    )
    parser.add_argument(
        "--golden",
        required=True,
        help="Path to golden truth directory",
    )
    parser.add_argument(
        "--attempt",
        action="append",
        required=True,
        dest="attempts",
        help="Named attempt in 'name=/path' format",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Migration target (e.g., 'patternfly')",
    )
    parser.add_argument(
        "--before-migration",
        default=None,
        help="Path to the source codebase before any migration was applied",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum debate rounds (default: 3)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    golden_dir = Path(args.golden).resolve()
    before_migration_dir: Path | None = None
    if args.before_migration:
        before_migration_dir = Path(args.before_migration).resolve()

    # Parse attempts
    attempt_map: dict[str, Path] = {}
    for attempt_str in args.attempts:
        if "=" not in attempt_str:
            print(f"Error: --attempt must be 'name=/path', got: {attempt_str}", file=sys.stderr)
            sys.exit(1)
        name, path = attempt_str.split("=", 1)
        attempt_map[name.strip()] = Path(path.strip()).resolve()

    claude_bin = find_claude_binary()
    print(f"Using claude: {claude_bin}")

    # Add scripts dir to path for imports
    scripts_dir = str(Path(__file__).parent.resolve())
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # Run review for each attempt
    review_results: list[dict[str, Any]] = []
    for attempt_name, attempt_dir in attempt_map.items():
        print(f"\n{'='*60}")
        print(f"  LLM Review: {attempt_name}")
        print(f"{'='*60}")

        # Prepare review input
        review_input = prepare_review_input(
            golden_dir, attempt_dir, attempt_name, output_dir, args.target,
            before_migration_dir=before_migration_dir,
        )
        print(f"  Files selected for review: {review_input['file_count']}")

        if review_input["file_count"] == 0:
            print(f"  No files to review, skipping")
            continue

        # Run adversarial loop
        result = run_review_loop(
            claude_bin, review_input, attempt_name, output_dir, args.max_rounds,
        )
        review_results.append(result)

    # Build consolidated assessment
    if review_results:
        build_llm_assessment(review_results, output_dir)
    else:
        print("\nNo review results to consolidate")

    print(str(output_dir))


if __name__ == "__main__":
    main()
