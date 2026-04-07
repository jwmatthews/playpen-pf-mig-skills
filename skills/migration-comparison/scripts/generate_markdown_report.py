#!/usr/bin/env python3
"""
Generate a markdown evaluation report from evaluation-results.json.

Designed to be both human-readable and LLM-consumable — structured so a
planning agent can parse it to decide what to fix next.

CLI: python3 generate_markdown_report.py <work_dir> [--output path]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _build_diff_index(comparison_data: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Build index: attempt -> file_path -> text_diff."""
    index: dict[str, dict[str, str]] = {}
    for attempt_name, comp_data in comparison_data.items():
        file_diffs: dict[str, str] = {}
        for f in comp_data.get("files", {}).get("modified", []):
            path = f.get("path", "")
            diff = f.get("text_diff", "")
            if path and diff:
                file_diffs[path] = diff
        index[attempt_name] = file_diffs
    return index


def _build_pattern_detail_index(
    pairwise_data: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Build index: attempt -> pattern_id -> [file details]."""
    index: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for attempt_name, scoring in pairwise_data.items():
        by_pattern: dict[str, list[dict[str, Any]]] = {}
        for pr in scoring.get("pattern_results", []):
            pid = pr.get("pattern_id", "")
            details = pr.get("details", [])
            if pid and details:
                by_pattern[pid] = details
        index[attempt_name] = by_pattern
    return index


def _truncate_diff(diff_text: str, max_lines: int = 25) -> str:
    """Truncate a diff to max_lines, adding a note if truncated."""
    lines = diff_text.strip().split("\n")
    if len(lines) <= max_lines:
        return diff_text.strip()
    truncated = "\n".join(lines[:max_lines])
    return f"{truncated}\n... ({len(lines) - max_lines} more lines)"


def generate_markdown(
    data: dict[str, Any],
    comparison_data: dict[str, dict[str, Any]] | None = None,
    llm_assessment: dict[str, Any] | None = None,
    scorecard: dict[str, Any] | None = None,
) -> str:
    if comparison_data is None:
        comparison_data = {}
    if scorecard is None:
        scorecard = {}

    metadata = data.get("metadata", {})
    attempt_scores = data.get("attempt_scores", {})
    attempt_names = sorted(attempt_scores.keys())
    pairwise_data = data.get("pairwise_data", {})

    diff_index = _build_diff_index(comparison_data)
    pattern_detail_index = _build_pattern_detail_index(pairwise_data)

    lines: list[str] = []

    # Header
    lines.append("# Migration Evaluation Report")
    lines.append("")
    target = metadata.get("target", "")
    if target:
        lines.append(f"**Target:** {target}")
    lines.append(f"**Attempts:** {', '.join(attempt_names)}")
    lines.append("")

    # Summary scores
    lines.append("## Summary")
    lines.append("")
    for name in attempt_names:
        score = attempt_scores.get(name, {})
        grade = score.get("composite_grade", score.get("grade", "?"))
        percent = score.get("composite_percent", score.get("overall_percent", 0))
        points = score.get("composite_points", score.get("points", 0))
        pos = score.get("positive_points", 0)
        neg = score.get("negative_points", 0)
        lines.append(f"- **{name}**: {grade} ({percent}%) | **{points:+.1f} pts** (+{pos:.1f} / {neg:.1f})")
    lines.append("")

    # Per-pattern scorecard
    lines.append("## Pattern Scorecard")
    lines.append("")

    # Gather all patterns across attempts from scorecard
    all_patterns: list[dict[str, Any]] = []
    seen_pids: set[str] = set()

    if scorecard:
        for attempt_name, attempt_data in scorecard.get("attempts", {}).items():
            for finding in attempt_data.get("deterministic_findings", []):
                pid = finding.get("id", "")
                if pid in seen_pids:
                    # Update existing
                    for p in all_patterns:
                        if p["id"] == pid:
                            p["statuses"][attempt_name] = finding.get("status", "unknown")
                            p["details_by_attempt"][attempt_name] = finding.get("files", [])
                    continue
                seen_pids.add(pid)
                all_patterns.append({
                    "id": pid,
                    "name": finding.get("name", pid),
                    "description": finding.get("description", ""),
                    "complexity": finding.get("complexity", "moderate"),
                    "statuses": {attempt_name: finding.get("status", "unknown")},
                    "details_by_attempt": {attempt_name: finding.get("files", [])},
                })

    # Fallback to pairwise_data
    for attempt_name, scoring in pairwise_data.items():
        for pr in scoring.get("pattern_results", []):
            pid = pr.get("pattern_id", "")
            status = pr.get("status", "not_applicable")
            if status == "not_applicable":
                continue
            if pid not in seen_pids:
                seen_pids.add(pid)
                all_patterns.append({
                    "id": pid,
                    "name": pr.get("name", pid),
                    "description": "",
                    "complexity": pr.get("complexity", "moderate"),
                    "statuses": {attempt_name: status},
                    "details_by_attempt": {attempt_name: pr.get("files", [])},
                })
            else:
                for p in all_patterns:
                    if p["id"] == pid:
                        if attempt_name not in p["statuses"]:
                            p["statuses"][attempt_name] = status
                        p["details_by_attempt"].setdefault(attempt_name, pr.get("files", []))

    for pattern in all_patterns:
        pid = pattern["id"]
        name = pattern["name"]
        desc = pattern["description"]
        complexity = pattern["complexity"]

        # Status summary across attempts
        status_parts = []
        for aname in attempt_names:
            s = pattern["statuses"].get(aname, "n/a")
            status_parts.append(f"{aname}: `{s}`")

        lines.append(f"### {name}")
        lines.append("")
        if desc:
            lines.append(f"> {desc}")
            lines.append("")
        lines.append(f"**Complexity:** {complexity} | {' | '.join(status_parts)}")
        lines.append("")

        # Per-attempt file details
        for aname in attempt_names:
            attempt_files = pattern["details_by_attempt"].get(aname, [])
            if not attempt_files:
                continue

            details = pattern_detail_index.get(aname, {}).get(pid, [])
            detail_by_file = {d.get("file", ""): d for d in details}
            attempt_diffs = diff_index.get(aname, {})

            if len(attempt_names) > 1:
                lines.append(f"**{aname}:**")
                lines.append("")

            for fp in attempt_files:
                detail = detail_by_file.get(fp, {})
                status = detail.get("status", "")
                message = detail.get("message", "")
                diff_text = attempt_diffs.get(fp, "")

                status_str = f" `{status}`" if status else ""
                msg_str = f" — {message}" if message else ""
                lines.append(f"- `{fp}`{status_str}{msg_str}")

                # Include diff snippet for non-correct statuses or if it's short
                if diff_text and status != "correct":
                    snippet = _truncate_diff(diff_text, max_lines=20)
                    lines.append("")
                    lines.append("  <details>")
                    lines.append(f"  <summary>diff ({len(diff_text.splitlines())} lines)</summary>")
                    lines.append("")
                    lines.append("  ```diff")
                    for dl in snippet.split("\n"):
                        lines.append(f"  {dl}")
                    lines.append("  ```")
                    lines.append("")
                    lines.append("  </details>")
                    lines.append("")

            lines.append("")

    # Problem areas
    problem_areas = data.get("problem_areas", [])
    llm_themes: list[dict[str, Any]] = []
    if scorecard:
        for aname, adata in scorecard.get("attempts", {}).items():
            for theme in adata.get("llm_themes", []):
                llm_themes.append({**theme, "attempt": aname})

    if problem_areas or llm_themes:
        lines.append("## Problem Areas")
        lines.append("")

        # Merge and deduplicate
        all_problems: list[dict[str, Any]] = []
        seen_titles: set[str] = set()

        for pa in problem_areas:
            all_problems.append({
                "severity": pa.get("severity", "medium"),
                "title": pa.get("description", ""),
                "description": pa.get("recommendation", ""),
                "files": pa.get("affected_files", []),
                "source": pa.get("source", "deterministic"),
                "attempt": pa.get("attempt", ""),
            })
            seen_titles.add(pa.get("description", "").lower())

        for theme in llm_themes:
            title = theme.get("theme", theme.get("description", ""))
            if title.lower() not in seen_titles:
                all_problems.append({
                    "severity": theme.get("severity", "medium"),
                    "title": title,
                    "description": theme.get("description", ""),
                    "files": theme.get("affected_files", []),
                    "source": "llm",
                    "attempt": theme.get("attempt", ""),
                })

        for sev in ["critical", "high", "medium", "low"]:
            sev_problems = [p for p in all_problems if p["severity"] == sev]
            if not sev_problems:
                continue

            lines.append(f"### {sev.upper()} ({len(sev_problems)})")
            lines.append("")

            for p in sev_problems:
                attempt = p.get("attempt", "")
                source = p.get("source", "")
                source_label = "rule-based" if source == "deterministic" else "AI-identified"
                attempt_str = f" ({attempt})" if attempt else ""
                lines.append(f"- **{p['title']}**{attempt_str} [{source_label}]")
                if p["description"] and p["description"].lower() != p["title"].lower():
                    lines.append(f"  {p['description']}")
                if p["files"]:
                    for fp in p["files"][:10]:
                        lines.append(f"  - `{fp}`")
                    if len(p["files"]) > 10:
                        lines.append(f"  - ... and {len(p['files']) - 10} more")
                lines.append("")

    # LLM file assessments (if available)
    if llm_assessment:
        file_assessments = llm_assessment.get("file_assessments", [])
        real_issues = [
            (fa, issue)
            for fa in file_assessments
            for issue in fa.get("issues", [])
            if issue.get("referee_verdict") == "real"
        ]

        if real_issues:
            lines.append("## LLM-Confirmed Issues")
            lines.append("")
            lines.append(f"{len(real_issues)} issues confirmed through adversarial debate:")
            lines.append("")

            for fa, issue in real_issues:
                attempt = fa.get("attempt", "")
                filepath = fa.get("file", "")
                sev = issue.get("severity", "medium")
                desc = issue.get("description", "")
                confidence = issue.get("referee_confidence", 0)
                lines.append(f"- **[{sev.upper()}]** `{filepath}` ({attempt}, confidence: {confidence:.0%})")
                if desc:
                    # Wrap long descriptions
                    lines.append(f"  {desc[:300]}{'...' if len(desc) > 300 else ''}")
                lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate markdown evaluation report from evaluation-results.json"
    )
    parser.add_argument(
        "work_dir",
        help="Path to the workspace directory containing evaluation-results.json",
    )
    parser.add_argument(
        "--output",
        help="Output path for the markdown report (default: <work_dir>/evaluation-report.md)",
    )

    args = parser.parse_args()
    work_dir = Path(args.work_dir)

    if not work_dir.is_dir():
        print(f"Error: Directory not found: {work_dir}", file=sys.stderr)
        sys.exit(1)

    results_path = work_dir / "evaluation-results.json"
    if not results_path.exists():
        print(f"Error: evaluation-results.json not found in {work_dir}", file=sys.stderr)
        sys.exit(1)

    with open(results_path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    # Load comparison data
    comparison_data: dict[str, dict[str, Any]] = {}
    for subdir in sorted(work_dir.iterdir()):
        if subdir.is_dir() and subdir.name.startswith("golden-vs-"):
            attempt_name = subdir.name.removeprefix("golden-vs-")
            comp_path = subdir / "comparison-data.json"
            if comp_path.exists():
                try:
                    with open(comp_path, "r", encoding="utf-8") as f:
                        comparison_data[attempt_name] = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

    # Load LLM assessment
    llm_assessment: dict[str, Any] | None = None
    llm_path = work_dir / "llm-assessment.json"
    if llm_path.exists():
        try:
            with open(llm_path, "r", encoding="utf-8") as f:
                llm_assessment = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Load scorecard
    scorecard: dict[str, Any] | None = None
    scorecard_path = work_dir / "scorecard.json"
    if scorecard_path.exists():
        try:
            with open(scorecard_path, "r", encoding="utf-8") as f:
                scorecard = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    md_output = generate_markdown(
        data,
        comparison_data=comparison_data,
        llm_assessment=llm_assessment,
        scorecard=scorecard,
    )

    output_path = Path(args.output) if args.output else work_dir / "evaluation-report.md"
    output_path.write_text(md_output, encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
