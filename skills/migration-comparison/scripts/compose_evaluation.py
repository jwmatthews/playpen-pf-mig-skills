#!/usr/bin/env python3
"""
Compose evaluation results from pairwise scoring and LLM assessment.

Reads all pairwise scoring-results.json files + optional llm-assessment.json,
produces evaluation-results.json with cross-attempt comparisons, problem areas,
and composite scores.

Usage:
    python3 scripts/compose_evaluation.py \
      --output-dir /tmp/eval-workspace \
      --golden /path/to/golden \
      --attempt ai-agent=/path/to/ai-output \
      --attempt codemods=/path/to/codemods-output \
      --target patternfly
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

from models import (
    AttemptComparison,
    AttemptScore,
    EvaluationMetadata,
    EvaluationResults,
    LLMAssessment,
    LLMSummary,
    PatternAdvantage,
    ProblemArea,
    ProblemAreaSource,
    ProblemAreaType,
    Severity,
)

# Composite scoring weights
WEIGHT_FILE_COVERAGE = 0.15
WEIGHT_DETERMINISTIC = 0.50
WEIGHT_NOISE = 0.10
WEIGHT_LLM = 0.25

# Grade thresholds
GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]


def grade_from_percent(percent: int) -> str:
    for threshold, letter in GRADE_THRESHOLDS:
        if percent >= threshold:
            return letter
    return "F"


def load_scoring_results(output_dir: Path, attempt_name: str) -> dict[str, Any] | None:
    """Load scoring-results.json for a specific attempt."""
    label = f"golden-vs-{attempt_name}"
    path = output_dir / label / "scoring-results.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


def load_comparison_data(output_dir: Path, attempt_name: str) -> dict[str, Any] | None:
    """Load comparison-data.json for a specific attempt."""
    label = f"golden-vs-{attempt_name}"
    path = output_dir / label / "comparison-data.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


def load_llm_assessment(output_dir: Path) -> LLMAssessment | None:
    """Load llm-assessment.json if present.

    Filters out not_real issues (they have null severity and shouldn't
    contribute to scoring or problem areas).
    """
    path = output_dir / "llm-assessment.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Filter out not_real issues before validation — referees set severity
    # to null for disproved issues, which fails Severity enum validation.
    for fa in data.get("file_assessments", []):
        fa["issues"] = [
            issue for issue in fa.get("issues", [])
            if issue.get("referee_verdict") != "not_real"
        ]

    return LLMAssessment.model_validate(data)


def compute_attempt_score(
    scoring: dict[str, Any],
    llm_assessment: LLMAssessment | None,
    attempt_name: str,
) -> AttemptScore:
    """Compute individual attempt score from deterministic + optional LLM results."""
    score_data = scoring.get("score", {})
    components = score_data.get("components", {})

    det_percent = score_data.get("overall_percent", 0)
    det_grade = score_data.get("grade", "F")
    det_points = score_data.get("points", 0.0)
    det_positive = score_data.get("positive_points", 0.0)
    det_negative = score_data.get("negative_points", 0.0)

    # Extract component scores
    fc_score = components.get("file_coverage", {}).get("score", 0.0)
    ps_score = components.get("pattern_score", {}).get("score", 0.0)
    ps_points = components.get("pattern_score", {}).get("points", 0.0)
    np_penalty = components.get("noise_penalty", {}).get("raw_penalty", 0.0)
    np_capped = min(np_penalty, 1.0)

    # LLM score (if available)
    llm_score: float | None = None
    if llm_assessment:
        attempt_assessments = [
            fa for fa in llm_assessment.file_assessments
            if fa.attempt == attempt_name
        ]
        if attempt_assessments:
            llm_score = sum(fa.summary_score for fa in attempt_assessments) / len(attempt_assessments)

    # Composite score (percentage-based, for backwards compat)
    if llm_score is not None:
        composite = (
            WEIGHT_FILE_COVERAGE * fc_score
            + WEIGHT_DETERMINISTIC * ps_score
            + WEIGHT_NOISE * (1.0 - np_capped)
            + WEIGHT_LLM * llm_score
        )
    else:
        adjusted_det_weight = WEIGHT_DETERMINISTIC + WEIGHT_LLM
        composite = (
            WEIGHT_FILE_COVERAGE * fc_score
            + adjusted_det_weight * ps_score
            + WEIGHT_NOISE * (1.0 - np_capped)
        )

    composite_percent = int(round(composite * 100))
    composite_grade = grade_from_percent(composite_percent)

    # Composite points: pattern points + LLM bonus/penalty
    composite_points = det_points
    if llm_score is not None:
        # LLM issues confirmed as "real" count as deductions
        attempt_issues = [
            issue
            for fa in (llm_assessment.file_assessments if llm_assessment else [])
            if fa.attempt == attempt_name
            for issue in fa.issues
            if issue.referee_verdict == "real"
        ]
        llm_deductions = sum(
            2.0 if issue.severity == "high" else 1.0
            for issue in attempt_issues
        )
        composite_points -= llm_deductions

    return AttemptScore(
        overall_percent=det_percent,
        grade=det_grade,
        points=det_points,
        positive_points=det_positive,
        negative_points=det_negative,
        deterministic_percent=det_percent,
        llm_score=llm_score,
        composite_percent=composite_percent,
        composite_grade=composite_grade,
        composite_points=round(composite_points, 2),
        components={
            "file_coverage": fc_score,
            "pattern_score": ps_score,
            "pattern_points": ps_points,
            "noise_penalty": np_capped,
            "llm_score": llm_score,
        },
    )


def compare_attempts(
    scoring_a: dict[str, Any],
    scoring_b: dict[str, Any],
    name_a: str,
    name_b: str,
) -> AttemptComparison:
    """Compare two attempts based on pattern results."""
    score_a = scoring_a.get("score", {})
    score_b = scoring_b.get("score", {})
    delta = score_a.get("overall_percent", 0) - score_b.get("overall_percent", 0)

    patterns_a = {p["pattern_id"]: p for p in scoring_a.get("pattern_results", [])}
    patterns_b = {p["pattern_id"]: p for p in scoring_b.get("pattern_results", [])}

    all_pattern_ids = sorted(set(patterns_a.keys()) | set(patterns_b.keys()))

    a_advantages: list[PatternAdvantage] = []
    b_advantages: list[PatternAdvantage] = []
    ties: list[str] = []
    neither: list[str] = []

    for pid in all_pattern_ids:
        pa = patterns_a.get(pid)
        pb = patterns_b.get(pid)
        status_a = pa["status"] if pa else "not_applicable"
        status_b = pb["status"] if pb else "not_applicable"
        name = pa["name"] if pa else (pb["name"] if pb else pid)

        if status_a == "not_applicable" and status_b == "not_applicable":
            continue

        a_correct = status_a == "correct"
        b_correct = status_b == "correct"

        if a_correct and b_correct:
            ties.append(pid)
        elif a_correct and not b_correct:
            a_advantages.append(PatternAdvantage(
                pattern_id=pid, name=name, a_status=status_a, b_status=status_b,
            ))
        elif b_correct and not a_correct:
            b_advantages.append(PatternAdvantage(
                pattern_id=pid, name=name, a_status=status_a, b_status=status_b,
            ))
        else:
            neither.append(pid)

    return AttemptComparison(
        delta=delta,
        a_advantages=a_advantages,
        b_advantages=b_advantages,
        ties=ties,
        neither=neither,
    )


def identify_problem_areas(
    scoring_data: dict[str, dict[str, Any]],
    llm_assessment: LLMAssessment | None,
) -> list[ProblemArea]:
    """Identify problem areas from deterministic and LLM sources."""
    problems: list[ProblemArea] = []

    # Deterministic problem areas: patterns that failed across attempts
    for attempt_name, scoring in scoring_data.items():
        pattern_results: list[dict[str, Any]] = scoring.get("pattern_results", [])

        for pr in pattern_results:
            status = pr.get("status", "not_applicable")
            if status in ("incorrect", "missing", "file_missing"):
                severity = Severity.high if pr.get("complexity") == "complex" else (
                    Severity.medium if pr.get("complexity") == "moderate" else Severity.low
                )
                if status == "incorrect":
                    severity = Severity.high

                affected_files = [d["file"] for d in pr.get("details", []) if d.get("status") != "correct"]

                problems.append(ProblemArea(
                    type=ProblemAreaType.pattern_cluster,
                    source=ProblemAreaSource.deterministic,
                    severity=severity,
                    attempt=attempt_name,
                    pattern_ids=[pr["pattern_id"]],
                    affected_files=affected_files,
                    description=f"{pr.get('name', pr['pattern_id'])}: {pr.get('message', status)}",
                    recommendation=_recommendation_for_pattern(pr),
                ))

    # LLM problem areas
    if llm_assessment:
        for fa in llm_assessment.file_assessments:
            confirmed_issues = [
                issue for issue in fa.issues
                if issue.referee_verdict.value == "real"
            ]
            if confirmed_issues:
                for issue in confirmed_issues:
                    problems.append(ProblemArea(
                        type=ProblemAreaType.llm_finding,
                        source=ProblemAreaSource.adversarial,
                        severity=issue.severity,
                        attempt=fa.attempt,
                        affected_files=[fa.file],
                        description=issue.description,
                        referee_confidence=issue.referee_confidence,
                    ))

    # Sort by severity
    severity_order = {Severity.critical: 0, Severity.high: 1, Severity.medium: 2, Severity.low: 3}
    problems.sort(key=lambda p: severity_order.get(p.severity, 3))

    return problems


def _recommendation_for_pattern(pr: dict[str, Any]) -> str:
    """Generate a recommendation for a failed pattern."""
    status = pr.get("status", "")
    name = pr.get("name", pr.get("pattern_id", ""))
    complexity = pr.get("complexity", "moderate")

    if status == "incorrect":
        return f"Review and fix the {name} migration — the pattern was applied incorrectly"
    elif status == "missing":
        if complexity == "complex":
            return f"Add targeted examples for {name} to the agent prompt — complex patterns need explicit guidance"
        return f"Ensure the {name} migration pattern is applied"
    elif status == "file_missing":
        return f"Ensure all relevant files are included in the migration output"
    return ""


PATTERN_DESCRIPTIONS: dict[str, str] = {
    "css-class-prefix": "PF6 renamed CSS class prefixes from pf-v5- to pf-v6-. All CSS selectors and class references must be updated.",
    "utility-class-rename": "PF6 renamed utility classes from pf-u-* to pf-v6-u-*.",
    "css-logical-properties": "PF6 adopted CSS logical properties (e.g., paddingInlineStart instead of paddingLeft) for better RTL support.",
    "theme-dark-removal": "PF6 removed the dark theme variant. Components using ThemeVariant.dark or pf-theme-dark must be updated.",
    "inner-ref-to-ref": "PF6 renamed the innerRef prop to ref on components.",
    "align-right-to-end": "PF6 renamed alignment props from right/left to end/start for internationalization.",
    "is-action-cell": "PF6 removed isActionCell prop in favor of hasAction.",
    "space-items-removal": "PF6 removed the spaceItems prop from components.",
    "ouia-component-id": "PF6 standardized OUIA component IDs.",
    "chips-to-labels": "PF6 removed Chip/ChipGroup components. Replace with Label/LabelGroup.",
    "split-button-items": "PF6 renamed splitButtonOptions to splitButtonItems.",
    "modal-import-path": "PF6 moved Modal to react-core/next or deprecated paths.",
    "text-content-consolidation": "PF6 consolidated TextContent, TextList, Text into a single Content component.",
    "empty-state-restructure": "PF6 restructured EmptyState — EmptyStateHeader/EmptyStateIcon replaced with titleText prop.",
    "toolbar-variant": "PF6 renamed toolbar variant values (chip-group → label-group, etc.).",
    "toolbar-gap": "PF6 replaced toolbar spacer props with CSS gap/columnGap/rowGap.",
    "button-icon-prop": "PF6 changed Button icon API to use an icon prop.",
    "page-section-variant": "PF6 removed PageSection variant='light'/'dark'/'darker' and PageSectionVariants enum.",
    "page-masthead": "PF6 replaced PageHeader with Masthead component.",
    "react-tokens-icon-status": "PF6 renamed react-tokens imports from global_* to t_* format.",
    "avatar-props": "PF6 updated Avatar component props.",
    "select-rewrite": "PF6 replaced the Select component with a new MenuToggle+SelectList pattern. Requires restructuring component composition.",
    "masthead-reorganization": "PF6 reorganized Masthead — MastheadToggle removed, MastheadLogo added.",
    "test-selector-rewrite": "PF6 changed test selectors from pf-v5- to pf-v6- CSS class prefixes.",
}


def build_scorecard(
    scoring_data: dict[str, dict[str, Any]],
    attempt_scores: dict[str, "AttemptScore"],
    comparisons: dict[str, "AttemptComparison"],
    llm_themes: list[dict[str, Any]],
    target: str | None,
    golden_dir: str,
) -> dict[str, Any]:
    """Build scorecard.json — flat, diffable, per-pattern pass/fail per attempt."""
    from datetime import datetime, timezone

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d") + ("-" + target if target else "")
    attempt_names = sorted(scoring_data.keys())

    # Build per-attempt scorecard entries
    attempts_scorecard: dict[str, Any] = {}
    for name in attempt_names:
        scoring = scoring_data[name]
        score = attempt_scores.get(name)

        deterministic_findings: list[dict[str, Any]] = []
        for pr in scoring.get("pattern_results", []):
            if pr.get("status") == "not_applicable":
                continue
            description = PATTERN_DESCRIPTIONS.get(pr["pattern_id"], "")
            finding: dict[str, Any] = {
                "id": pr["pattern_id"],
                "name": pr.get("name", pr["pattern_id"]),
                "description": description,
                "complexity": pr.get("complexity", "moderate"),
                "status": pr.get("status", "unknown"),
                "detail": pr.get("message", ""),
                "files": pr.get("files", []),
            }
            deterministic_findings.append(finding)

        # LLM themes for this attempt
        attempt_themes: list[dict[str, Any]] = []
        for theme in llm_themes:
            if theme.get("attempt") == name:
                attempt_themes.append({
                    "severity": theme.get("severity", "medium"),
                    "theme": theme.get("theme", ""),
                    "description": theme.get("description", ""),
                    "affected_files": theme.get("affected_files", []),
                    "confidence": theme.get("confidence", 0.5),
                })

        attempts_scorecard[name] = {
            "overall_grade": score.composite_grade or score.grade if score else "?",
            "overall_percent": score.composite_percent or score.overall_percent if score else 0,
            "points": score.composite_points if score and score.composite_points is not None else (score.points if score else 0),
            "positive_points": score.positive_points if score else 0,
            "negative_points": score.negative_points if score else 0,
            "deterministic_findings": deterministic_findings,
            "llm_themes": attempt_themes,
        }

    # Build comparison section
    comparison_section: dict[str, list[dict[str, str]]] = {
        "ai_leads_on": [],
        "codemods_leads_on": [],
        "both_correct": [],
        "both_wrong": [],
    }

    # Use first comparison if available
    if comparisons:
        first_key = next(iter(comparisons))
        comp = comparisons[first_key]
        names = first_key.split("_vs_")
        name_a = names[0] if len(names) >= 2 else attempt_names[0] if attempt_names else ""
        name_b = names[1] if len(names) >= 2 else (attempt_names[1] if len(attempt_names) > 1 else "")

        # Map pattern IDs to names
        all_patterns: dict[str, str] = {}
        for scoring in scoring_data.values():
            for pr in scoring.get("pattern_results", []):
                all_patterns[pr["pattern_id"]] = pr.get("name", pr["pattern_id"])

        for adv in comp.a_advantages:
            comparison_section["ai_leads_on"].append({
                "name": adv.name or all_patterns.get(adv.pattern_id, adv.pattern_id),
                "id": adv.pattern_id,
            })
        for adv in comp.b_advantages:
            comparison_section["codemods_leads_on"].append({
                "name": adv.name or all_patterns.get(adv.pattern_id, adv.pattern_id),
                "id": adv.pattern_id,
            })
        for pid in comp.ties:
            comparison_section["both_correct"].append({
                "name": all_patterns.get(pid, pid),
                "id": pid,
            })
        for pid in comp.neither:
            comparison_section["both_wrong"].append({
                "name": all_patterns.get(pid, pid),
                "id": pid,
            })

    scorecard: dict[str, Any] = {
        "run_id": run_id,
        "target": target,
        "golden_dir": golden_dir,
        "attempts": attempts_scorecard,
        "comparison": comparison_section,
    }

    return scorecard


def compute_llm_summary(llm_assessment: LLMAssessment) -> LLMSummary:
    """Compute summary statistics from LLM assessment."""
    total_issues = sum(len(fa.issues) for fa in llm_assessment.file_assessments)
    confirmed = sum(
        1 for fa in llm_assessment.file_assessments
        for issue in fa.issues
        if issue.referee_verdict.value == "real"
    )
    avg_score = 0.0
    if llm_assessment.file_assessments:
        avg_score = sum(fa.summary_score for fa in llm_assessment.file_assessments) / len(llm_assessment.file_assessments)

    return LLMSummary(
        files_assessed=llm_assessment.metadata.files_assessed,
        issues_found=total_issues,
        issues_confirmed=confirmed,
        average_file_score=round(avg_score, 4),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compose evaluation results from pairwise scoring and LLM assessment"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory containing pairwise artifacts and llm-assessment.json",
    )
    parser.add_argument(
        "--golden",
        required=True,
        help="Path to golden truth directory (for metadata)",
    )
    parser.add_argument(
        "--attempt",
        action="append",
        required=True,
        dest="attempts",
        help="Named attempt in 'name=/path' format",
    )
    parser.add_argument(
        "--before-migration",
        default=None,
        help="Path to the source codebase before any migration (for metadata)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Migration target (for metadata)",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    # Parse attempts
    attempt_map: dict[str, str] = {}
    for attempt_str in args.attempts:
        if "=" not in attempt_str:
            print(f"Error: --attempt must be 'name=/path', got: {attempt_str}", file=sys.stderr)
            sys.exit(1)
        name, path = attempt_str.split("=", 1)
        attempt_map[name.strip()] = path.strip()

    attempt_names = sorted(attempt_map.keys())

    # Load all scoring results
    scoring_data: dict[str, dict[str, Any]] = {}
    for name in attempt_names:
        scoring = load_scoring_results(output_dir, name)
        if scoring is None:
            print(f"Warning: No scoring results found for attempt '{name}'", file=sys.stderr)
            continue
        scoring_data[name] = scoring

    if not scoring_data:
        print("Error: No scoring results found for any attempt", file=sys.stderr)
        sys.exit(1)

    # Load LLM assessment (optional)
    llm_assessment = load_llm_assessment(output_dir)

    # Compute per-attempt scores
    attempt_scores: dict[str, AttemptScore] = {}
    for name in attempt_names:
        if name not in scoring_data:
            continue
        attempt_scores[name] = compute_attempt_score(
            scoring_data[name], llm_assessment, name,
        )

    # Cross-attempt comparisons
    comparisons: dict[str, AttemptComparison] = {}
    scored_names = [n for n in attempt_names if n in scoring_data]
    for name_a, name_b in combinations(scored_names, 2):
        key = f"{name_a}_vs_{name_b}"
        comparisons[key] = compare_attempts(
            scoring_data[name_a], scoring_data[name_b], name_a, name_b,
        )

    # Problem areas
    problem_areas = identify_problem_areas(scoring_data, llm_assessment)

    # LLM summary
    llm_summary: LLMSummary | None = None
    if llm_assessment:
        llm_summary = compute_llm_summary(llm_assessment)

    # Build pairwise data for report
    pairwise_data: dict[str, Any] = {}
    for name in scored_names:
        pairwise_data[name] = scoring_data[name]

    # Compose results
    meta_kwargs: dict[str, Any] = {
        "golden_dir": str(Path(args.golden).resolve()),
        "attempts": attempt_map,
        "target": args.target,
    }
    if args.before_migration:
        meta_kwargs["before_migration_dir"] = str(Path(args.before_migration).resolve())
    results = EvaluationResults(
        metadata=EvaluationMetadata(**meta_kwargs),
        attempt_scores={name: score for name, score in attempt_scores.items()},
        comparisons={key: comp for key, comp in comparisons.items()},
        problem_areas=problem_areas,
        llm_summary=llm_summary,
        pairwise_data=pairwise_data,
    )

    # Write evaluation results
    output_path = output_dir / "evaluation-results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(results.model_dump_json(indent=2))

    print(f"Evaluation results written to: {output_path}")

    # Load raw LLM themes (not in the pydantic model)
    llm_themes_raw: list[dict[str, Any]] = []
    llm_raw_path = output_dir / "llm-assessment.json"
    if llm_raw_path.exists():
        with open(llm_raw_path, "r", encoding="utf-8") as f:
            llm_raw = json.load(f)
        llm_themes_raw = llm_raw.get("themes", [])

    # Build and write scorecard
    scorecard = build_scorecard(
        scoring_data=scoring_data,
        attempt_scores=attempt_scores,
        comparisons=comparisons,
        llm_themes=llm_themes_raw,
        target=args.target,
        golden_dir=str(Path(args.golden).resolve()),
    )
    scorecard_path = output_dir / "scorecard.json"
    with open(scorecard_path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)

    print(f"Scorecard written to: {scorecard_path}")

    # Print summary
    print(f"\n{'='*60}")
    print("  Composite Evaluation Summary")
    print(f"{'='*60}")
    for name, score in attempt_scores.items():
        pts_str = f" | Points: {score.points:+.1f}"
        composite_str = ""
        if score.composite_percent is not None:
            composite_str = f" → Composite: {score.composite_grade} ({score.composite_percent}%)"
            if score.composite_points is not None:
                composite_str += f" [{score.composite_points:+.1f} pts]"
        llm_str = f", LLM: {score.llm_score:.0%}" if score.llm_score is not None else ""
        print(f"  {name}: Det: {score.grade} ({score.overall_percent}%){pts_str}{llm_str}{composite_str}")

    if problem_areas:
        print(f"\n  Problem areas identified: {len(problem_areas)}")
        for pa in problem_areas[:5]:
            print(f"    [{pa.severity.value.upper()}] {pa.attempt}: {pa.description}")
        if len(problem_areas) > 5:
            print(f"    ... and {len(problem_areas) - 5} more")

    print(str(output_path))


if __name__ == "__main__":
    main()
