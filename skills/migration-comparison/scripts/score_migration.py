#!/usr/bin/env python3
"""
Migration quality scoring engine.

Computes a quality score for a migration candidate by comparing it against
a reference migration. Supports generic scoring (file coverage, noise detection)
and target-specific pattern detectors (e.g., PatternFly 5→6).

Produces scoring-results.json in the workspace directory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Noise penalty values per instance
NOISE_PENALTIES: dict[str, float] = {
    "unnecessary_change": 0.01,
    "formatting_only": 0.02,
    "incorrect_migration": 0.03,
    "artifact": 0.05,
    "placeholder_token": 0.05,
}

# Score weights
WEIGHT_FILE_COVERAGE = 0.20
WEIGHT_PATTERN_SCORE = 0.65
WEIGHT_NOISE = 0.15

# Grade scale
GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]

# Files to exclude from file coverage calculations
EXCLUDED_PATTERNS: list[str] = [
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"\.snap$",
    r"__snapshots__/",
    r"node_modules/",
]

# Artifact patterns to scan for in candidate files
ARTIFACT_PATTERNS: list[tuple[str, str]] = [
    (r"\bconsole\.log\b", "console.log statement"),
    (r"\bdebugger\b", "debugger statement"),
    (r"@ts-ignore", "@ts-ignore directive"),
    (r"@ts-nocheck", "@ts-nocheck directive"),
]

# Placeholder token patterns
PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    (r"\bFIXME\b", "FIXME token"),
    (r"\bHACK\b", "HACK token"),
    (r"\bTODO\b", "TODO token"),
    (r"\bPLACEHOLDER\b", "PLACEHOLDER token"),
    (r"\bXXX\b", "XXX token"),
]


def _is_excluded(path: str) -> bool:
    """Check if a file path should be excluded from coverage calculations."""
    return any(re.search(pat, path) for pat in EXCLUDED_PATTERNS)


def _find_line_number(content: str | None, pattern: str) -> int | None:
    """Find the first line number (1-based) where pattern matches in content."""
    if not content:
        return None
    for i, line in enumerate(content.split("\n"), 1):
        if re.search(pattern, line):
            return i
    return None


# Patterns to search in candidate content for line-number enrichment.
# Maps (pattern_id, status) → regex to search in candidate content.
# "missing" status searches for old/un-migrated code; "correct" searches for new code.
_LINE_SEARCH_PATTERNS: dict[str, dict[str, str]] = {
    "css-class-prefix": {"correct": r"pf-v6-", "missing": r"pf-v5-"},
    "utility-class-rename": {"correct": r"pf-v6-u-", "missing": r"\bpf-u-\w"},
    "css-logical-properties": {"correct": r"(Padding|Margin)(Block|Inline)(Start|End)|(margin|padding)-(inline|block)"},
    "theme-dark-removal": {"missing": r"""theme\s*=\s*["']dark|ThemeVariant\.dark|pf-theme-dark"""},
    "inner-ref-to-ref": {"correct": r'\bref[=\s{]', "missing": r"\binnerRef\b"},
    "align-right-to-end": {"correct": r"\balignEnd\b", "missing": r"\balignRight\b"},
    "is-action-cell": {"correct": r"\bhasAction\b", "missing": r"\bisActionCell\b"},
    "space-items-removal": {"missing": r"\bspaceItems\b"},
    "chips-to-labels": {"correct": r"\bLabelGroup\b|\bLabel\b", "missing": r"\bChipGroup\b|\bChip\b"},
    "split-button-items": {"correct": r"\bsplitButtonItems\b", "missing": r"\bsplitButtonOptions\b"},
    "modal-import-path": {"correct": r"react-core/(next|deprecated).*Modal"},
    "text-content-consolidation": {"correct": r"\bContent\b", "missing": r"\bTextContent\b|\bTextList\b"},
    "empty-state-restructure": {"correct": r"\btitleText=", "missing": r"\bEmptyStateHeader\b|\bEmptyStateIcon\b"},
    "toolbar-variant": {"correct": r'variant=.*label-group', "missing": r"variant=.*(chip-group|bulk-select|overflow-menu)"},
    "toolbar-gap": {"correct": r"\bgap\b|\bcolumnGap\b|\browGap\b", "missing": r"\bspacer\b"},
    "button-icon-prop": {"correct": r"\bicon="},
    "page-section-variant": {"missing": r"""variant=\s*["']*(light|dark|darker)|PageSectionVariants"""},
    "page-masthead": {"correct": r"\bmasthead=|\bMasthead\b", "missing": r"\bPageHeader\b|\bheader="},
    "react-tokens-icon-status": {"correct": r"\bt_\w+", "missing": r"\bglobal_\w+"},
    "select-rewrite": {"correct": r"\bMenuToggle\b|\bSelectList\b", "missing": r"\bonToggle\b|\bisOpen\b|\bselections\b"},
    "masthead-reorganization": {"correct": r"\bMastheadLogo\b", "missing": r"\bMastheadToggle\b"},
    "test-selector-rewrite": {"correct": r"pf-v6-", "missing": r"pf-v5-"},
}


def _file_matches_before(path: str, dir_b: str, before_dir: str) -> bool:
    """Check if a candidate file is identical to its before-migration version.

    If True, the attempt didn't migrate this file at all.
    """
    cand = Path(dir_b) / path
    before = Path(before_dir) / path
    try:
        if not cand.exists() or not before.exists():
            return False
        return cand.read_bytes() == before.read_bytes()
    except OSError:
        return False


def _invert_diff(diff_text: str | None) -> str | None:
    """Invert a unified diff by swapping added/removed lines.

    The comparison-data text_diff is ref→cand (- = ref, + = cand).
    Inverting it produces cand→ref (- = cand, + = ref), which shows
    reference content as added lines — the perspective detectors expect
    for ref_diff.
    """
    if not diff_text:
        return diff_text
    lines: list[str] = []
    for line in diff_text.split("\n"):
        if line.startswith("---"):
            lines.append("+++ " + line[4:])
        elif line.startswith("+++"):
            lines.append("--- " + line[4:])
        elif line.startswith("-") and not line.startswith("---"):
            lines.append("+" + line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            lines.append("-" + line[1:])
        else:
            lines.append(line)
    return "\n".join(lines)


def compute_file_coverage(comparison_data: dict[str, Any]) -> dict[str, Any]:
    """Compute file coverage: matched / total_reference (excluding lockfiles, snapshots).

    Returns dict with score, matched, total, and details.
    """
    files = comparison_data.get("files", {})
    modified: list[dict[str, Any]] = files.get("modified", [])
    identical: list[dict[str, Any]] = files.get("identical", [])
    removed: list[dict[str, Any]] = files.get("removed", [])
    added: list[dict[str, Any]] = files.get("added", [])

    # Reference files = modified + identical + removed (files that exist in reference)
    # We exclude added files because they only exist in candidate
    ref_paths = set()
    for f in modified:
        p = f.get("path", "")
        if not _is_excluded(p):
            ref_paths.add(p)
    for f in identical:
        p = f.get("path", "") if isinstance(f, dict) else f
        if not _is_excluded(p):
            ref_paths.add(p)
    for f in removed:
        p = f.get("path", "")
        if not _is_excluded(p):
            ref_paths.add(p)

    # Matched = files present in both (modified + identical, not removed)
    matched_paths = set()
    for f in modified:
        p = f.get("path", "")
        if not _is_excluded(p):
            matched_paths.add(p)
    for f in identical:
        p = f.get("path", "") if isinstance(f, dict) else f
        if not _is_excluded(p):
            matched_paths.add(p)

    total = len(ref_paths)
    matched = len(matched_paths)
    score = matched / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "matched": matched,
        "total": total,
    }


def detect_noise(
    comparison_data: dict[str, Any],
    dir_a: str,
    dir_b: str,
    pattern_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan for noise artifacts in the candidate migration.

    Checks for:
    - Debug artifacts (console.log, debugger, @ts-ignore)
    - Placeholder tokens (FIXME, HACK, TODO, PLACEHOLDER, XXX)
    - Formatting-only changes
    - Unnecessary changes (files modified in candidate but not in reference)
    - Incorrect pattern migrations (from pattern detection results)
    """
    noise_instances: list[dict[str, Any]] = []
    files = comparison_data.get("files", {})
    modified: list[dict[str, Any]] = files.get("modified", [])

    for file_info in modified:
        path = file_info.get("path", "")
        if _is_excluded(path):
            continue

        categories: list[str] = file_info.get("categories", [])
        text_diff = file_info.get("text_diff", "") or ""

        # Formatting-only changes
        if categories == ["cosmetic"]:
            noise_instances.append({
                "type": "formatting_only",
                "file": path,
                "line": None,
                "detail": "File has only cosmetic/formatting changes",
                "penalty": NOISE_PENALTIES["formatting_only"],
            })
            continue

        # Scan diff additions for artifacts and placeholders
        for diff_line in text_diff.split("\n"):
            if not diff_line.startswith("+") or diff_line.startswith("+++"):
                continue

            line_content = diff_line[1:]

            # Artifact patterns
            for pattern, description in ARTIFACT_PATTERNS:
                if re.search(pattern, line_content):
                    noise_instances.append({
                        "type": "artifact",
                        "file": path,
                        "line": None,
                        "detail": f"Added {description}",
                        "penalty": NOISE_PENALTIES["artifact"],
                    })

            # Placeholder patterns
            for pattern, description in PLACEHOLDER_PATTERNS:
                # Only flag in non-comment context to reduce false positives
                if re.search(pattern, line_content):
                    noise_instances.append({
                        "type": "placeholder_token",
                        "file": path,
                        "line": None,
                        "detail": f"Contains {description}",
                        "penalty": NOISE_PENALTIES["placeholder_token"],
                    })

    # Check for unnecessary changes: files only in candidate "added" that
    # don't correspond to any reference file.  These are already tracked by
    # the comparison data's "added" list — files present only in dir_b.
    added: list[dict[str, Any]] = files.get("added", [])
    for f in added:
        path = f.get("path", "")
        if _is_excluded(path):
            continue
        noise_instances.append({
            "type": "unnecessary_change",
            "file": path,
            "line": None,
            "detail": "File added in candidate but not present in reference",
            "penalty": NOISE_PENALTIES["unnecessary_change"],
        })

    # Add noise instances for INCORRECT pattern detections (0.03 per instance)
    if pattern_results:
        for pr in pattern_results:
            for detail in pr.get("details", []):
                if detail.get("status") == "incorrect":
                    noise_instances.append({
                        "type": "incorrect_migration",
                        "file": detail.get("file", ""),
                        "line": None,
                        "detail": f"Incorrect pattern: {pr.get('name', pr.get('pattern_id', ''))} — {detail.get('message', '')}",
                        "penalty": NOISE_PENALTIES["incorrect_migration"],
                    })

    return noise_instances


def compute_noise_penalty(noise_instances: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute total noise penalty from noise instances. Capped at 1.0."""
    raw = sum(n.get("penalty", 0.0) for n in noise_instances)
    capped = min(raw, 1.0)
    return {
        "raw_penalty": round(raw, 4),
        "capped_penalty": round(capped, 4),
        "instance_count": len(noise_instances),
    }


def load_target_patterns(
    target: str, targets_dir: str | Path
) -> list[dict[str, Any]]:
    """Load target-specific pattern detectors from <targets_dir>/<target>_patterns.py.

    Uses importlib to dynamically load the module and call get_patterns().
    Returns an empty list if the module is not found.
    """
    targets_path = Path(targets_dir)
    module_path = targets_path / f"{target}_patterns.py"

    if not module_path.exists():
        print(
            f"Warning: Target patterns file not found: {module_path}",
            file=sys.stderr,
        )
        return []

    spec = importlib.util.spec_from_file_location(
        f"{target}_patterns", str(module_path)
    )
    if spec is None or spec.loader is None:
        print(
            f"Warning: Could not load target patterns from {module_path}",
            file=sys.stderr,
        )
        return []

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    get_patterns: Callable[[], list[dict[str, Any]]] | None = getattr(
        module, "get_patterns", None
    )
    if get_patterns is None:
        print(
            f"Warning: {module_path} does not export get_patterns()",
            file=sys.stderr,
        )
        return []

    return get_patterns()


def run_pattern_detectors(
    patterns: list[dict[str, Any]],
    comparison_data: dict[str, Any],
    dir_a: str,
    dir_b: str,
    before_migration_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Run each pattern detector against modified and removed files.

    For each modified file, runs all applicable detectors.
    For each removed file (present in reference but missing from candidate),
    runs detectors with null candidate data to detect FILE_MISSING status.
    Returns a list of pattern result dicts.
    """
    files = comparison_data.get("files", {})
    modified: list[dict[str, Any]] = files.get("modified", [])
    removed: list[dict[str, Any]] = files.get("removed", [])

    # Try to import tree-sitter for AST analysis
    try:
        from ast_helpers import parse_tsx, is_available as ts_available
    except ImportError:
        # Try relative import
        try:
            script_dir = str(Path(__file__).parent)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            from ast_helpers import parse_tsx, is_available as ts_available
        except ImportError:
            parse_tsx = None  # type: ignore[assignment]
            ts_available = lambda: False  # noqa: E731

    # Build file data for detectors
    file_data: list[dict[str, Any]] = []
    for file_info in modified:
        path = file_info.get("path", "")
        if _is_excluded(path):
            continue

        ref_path = Path(dir_a) / path
        cand_path = Path(dir_b) / path

        ref_content: str | None = None
        cand_content: str | None = None
        try:
            if ref_path.exists():
                ref_content = ref_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        try:
            if cand_path.exists():
                cand_content = cand_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

        ref_tree = None
        cand_tree = None
        if ts_available() and parse_tsx is not None:
            ext = Path(path).suffix.lower()
            if ext in (".tsx", ".ts", ".jsx", ".js"):
                if ref_content:
                    ref_tree = parse_tsx(ref_content)
                if cand_content:
                    cand_tree = parse_tsx(cand_content)

        # The text_diff in comparison-data is ref→cand (- = ref lines, + = cand lines).
        # Detectors expect ref_diff to show what the reference migration changed
        # (reference code as added lines) and cand_diff to show what the candidate
        # migration changed (candidate code as added lines).
        # So: ref_diff = inverted diff (swap +/-), cand_diff = diff as-is.
        raw_diff = file_info.get("text_diff")
        ref_diff = _invert_diff(raw_diff)
        cand_diff = raw_diff

        file_data.append({
            "path": path,
            "ref_diff": ref_diff,
            "cand_diff": cand_diff,
            "ref_content": ref_content,
            "cand_content": cand_content,
            "ref_tree": ref_tree,
            "cand_tree": cand_tree,
            "categories": file_info.get("categories", []),
            "file_missing": False,
        })

    # Add removed files (present in reference, missing from candidate)
    # These get null candidate data — detectors should return file_missing
    for file_info in removed:
        path = file_info.get("path", "")
        if _is_excluded(path):
            continue

        ref_path = Path(dir_a) / path
        ref_content = None
        ref_tree = None
        try:
            if ref_path.exists():
                ref_content = ref_path.read_text(encoding="utf-8", errors="replace")
                if ts_available() and parse_tsx is not None:
                    ext = Path(path).suffix.lower()
                    if ext in (".tsx", ".ts", ".jsx", ".js"):
                        ref_tree = parse_tsx(ref_content)
        except OSError:
            pass

        file_data.append({
            "path": path,
            "ref_diff": None,
            "cand_diff": None,
            "ref_content": ref_content,
            "cand_content": None,
            "ref_tree": ref_tree,
            "cand_tree": None,
            "categories": [],
            "file_missing": True,
        })

    # Run each pattern detector
    pattern_results: list[dict[str, Any]] = []
    for pattern in patterns:
        pattern_id = pattern["id"]
        detect_fn: Callable[..., dict[str, Any]] = pattern["detect"]
        files_checked: list[str] = []
        details: list[dict[str, Any]] = []
        aggregate_status = "not_applicable"

        for fd in file_data:
            # For removed files, if the reference content is relevant to
            # this pattern, report file_missing (credit=0)
            if fd["file_missing"]:
                # Only flag file_missing if the reference content might
                # be relevant — run the detector with null candidate
                try:
                    result = detect_fn(
                        ref_diff=None,
                        cand_diff=None,
                        ref_content=fd["ref_content"],
                        cand_content=None,
                        ref_tree=fd["ref_tree"],
                        cand_tree=None,
                        path=fd["path"],
                        categories=[],
                    )
                except Exception:
                    result = {
                        "pattern_id": pattern_id,
                        "status": "not_applicable",
                        "message": "",
                        "details": [],
                    }
                # If detector found the pattern relevant (not not_applicable),
                # override to file_missing since candidate file doesn't exist
                status = result.get("status", "not_applicable")
                if status != "not_applicable":
                    status = "file_missing"
                    result["status"] = "file_missing"
                    result["message"] = "File missing from candidate"
            else:
                try:
                    result = detect_fn(
                        ref_diff=fd["ref_diff"],
                        cand_diff=fd["cand_diff"],
                        ref_content=fd["ref_content"],
                        cand_content=fd["cand_content"],
                        ref_tree=fd["ref_tree"],
                        cand_tree=fd["cand_tree"],
                        path=fd["path"],
                        categories=fd["categories"],
                    )
                except Exception as e:
                    result = {
                        "pattern_id": pattern_id,
                        "status": "not_applicable",
                        "message": f"Detector error: {e}",
                        "details": [],
                    }
                status = result.get("status", "not_applicable")

            # Override: if the candidate file is identical to the
            # before-migration source, the attempt never migrated it.
            if (
                status != "not_applicable"
                and not fd["file_missing"]
                and before_migration_dir
                and _file_matches_before(fd["path"], dir_b, before_migration_dir)
            ):
                status = "not_migrated"
                result["message"] = "File unchanged from before migration"

            if status != "not_applicable":
                files_checked.append(fd["path"])
                # Enrich with line number and absolute path
                cand_path_abs = str(Path(dir_b) / fd["path"])
                search_pats = _LINE_SEARCH_PATTERNS.get(pattern_id, {})
                search_pat = search_pats.get(status) or search_pats.get("missing") or search_pats.get("correct")
                line_num = _find_line_number(fd["cand_content"], search_pat) if search_pat else None
                details.append({
                    "file": fd["path"],
                    "abs_path": cand_path_abs,
                    "line": line_num,
                    "status": status,
                    "message": result.get("message", ""),
                })

                # Aggregate: correct > incorrect > not_migrated > missing/file_missing > not_applicable
                if status == "correct" and aggregate_status in (
                    "not_applicable",
                    "missing",
                    "file_missing",
                    "not_migrated",
                ):
                    aggregate_status = "correct"
                elif status == "incorrect":
                    aggregate_status = "incorrect"
                elif status == "not_migrated" and aggregate_status in (
                    "not_applicable",
                    "missing",
                    "file_missing",
                ):
                    aggregate_status = "not_migrated"
                elif status in ("missing", "file_missing") and aggregate_status == "not_applicable":
                    aggregate_status = status

        pattern_results.append({
            "pattern_id": pattern_id,
            "name": pattern.get("name", pattern_id),
            "complexity": pattern.get("complexity", "moderate"),
            "weight": pattern.get("weight", 2),
            "status": aggregate_status,
            "message": _summarize_pattern(aggregate_status, details),
            "files": files_checked,
            "details": details,
        })

    return pattern_results


def _summarize_pattern(
    status: str, details: list[dict[str, Any]]
) -> str:
    """Generate a summary message for a pattern's overall result."""
    if not details:
        return "Not applicable to any files"
    correct = sum(1 for d in details if d["status"] == "correct")
    incorrect = sum(1 for d in details if d["status"] == "incorrect")
    missing = sum(1 for d in details if d["status"] == "missing")
    not_migrated = sum(1 for d in details if d["status"] == "not_migrated")
    total = len(details)

    parts: list[str] = []
    if correct:
        parts.append(f"{correct}/{total} correct")
    if incorrect:
        parts.append(f"{incorrect}/{total} incorrect")
    if missing:
        parts.append(f"{missing}/{total} missing")
    if not_migrated:
        parts.append(f"{not_migrated}/{total} not migrated")
    return ", ".join(parts) if parts else f"Status: {status}"


def compute_pattern_score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute uncapped additive pattern score from pattern results.

    Points system (per file instance, scaled by pattern weight):
      correct:      +weight   (you did the right thing)
      incorrect:    -weight   (you broke something)
      missing:       0        (didn't attempt — neutral)
      not_migrated:  0        (didn't touch — neutral)
      file_missing:  0        (file not present — neutral)

    The score is uncapped: positive points for correct work, negative for
    broken work, zero for untouched. This lets us compare attempts by raw
    value delivered rather than penalizing for not touching everything.
    """
    points_map: dict[str, float] = {
        "correct": 1.0,
        "incorrect": -1.0,
        "missing": 0.0,
        "file_missing": 0.0,
        "not_migrated": 0.0,
    }

    total_points = 0.0
    positive_points = 0.0
    negative_points = 0.0
    by_complexity: dict[str, dict[str, Any]] = {}
    by_status: dict[str, int] = {}

    for result in results:
        status = result.get("status", "not_applicable")
        if status == "not_applicable":
            continue

        weight = result.get("weight", 2)
        points = points_map.get(status, 0.0) * weight
        total_points += points
        if points > 0:
            positive_points += points
        elif points < 0:
            negative_points += points

        by_status[status] = by_status.get(status, 0) + 1

        complexity = result.get("complexity", "moderate")
        if complexity not in by_complexity:
            by_complexity[complexity] = {"total": 0, "correct": 0, "incorrect": 0, "missing": 0}
        by_complexity[complexity]["total"] += 1
        by_complexity[complexity][status] = by_complexity[complexity].get(status, 0) + 1

    # Also compute a 0-1 ratio for backwards compat (correct / applicable)
    applicable = sum(1 for r in results if r.get("status", "not_applicable") != "not_applicable")
    correct_count = by_status.get("correct", 0)
    score_ratio = correct_count / applicable if applicable > 0 else 0.0

    return {
        "score": round(score_ratio, 4),
        "points": round(total_points, 2),
        "positive_points": round(positive_points, 2),
        "negative_points": round(negative_points, 2),
        "by_status": by_status,
        "by_complexity": by_complexity,
    }


def compute_generic_pattern_score(comparison_data: dict[str, Any]) -> dict[str, Any]:
    """Compute a heuristic pattern score when no target patterns are loaded.

    Uses category distribution: api_changes + semantic = good signals,
    cosmetic-only = bad signal.
    """
    categories = comparison_data.get("categories", {})
    files = comparison_data.get("files", {})
    modified: list[dict[str, Any]] = files.get("modified", [])

    if not modified:
        return {"score": 1.0, "method": "generic", "by_complexity": {}}

    # Count files by category type
    good_cats = set(categories.get("api_changes", {}).get("files", []))
    good_cats.update(categories.get("semantic", {}).get("files", []))
    cosmetic_only: set[str] = set()

    for f in modified:
        path = f.get("path", "")
        cats = f.get("categories", [])
        if cats == ["cosmetic"]:
            cosmetic_only.add(path)

    total = len(modified)
    good = len(good_cats)
    bad = len(cosmetic_only)

    # Higher proportion of meaningful changes = better score
    if total == 0:
        score = 1.0
    else:
        meaningful_ratio = good / total
        cosmetic_penalty = bad / total * 0.2
        score = min(1.0, max(0.0, meaningful_ratio * 0.8 + 0.4 - cosmetic_penalty))

    return {
        "score": round(score, 4),
        "method": "generic",
        "by_complexity": {},
    }


def compute_final_score(
    file_coverage: float,
    pattern_score: float,
    noise_penalty: float,
    pattern_points: float = 0.0,
    positive_points: float = 0.0,
    negative_points: float = 0.0,
    noise_count: int = 0,
) -> dict[str, Any]:
    """Compute final composite score using both points and percentage.

    Points = pattern_points - noise deductions
    Percentage is kept for backwards compat / grading.
    """
    weighted_fc = WEIGHT_FILE_COVERAGE * file_coverage
    weighted_ps = WEIGHT_PATTERN_SCORE * pattern_score
    weighted_noise = WEIGHT_NOISE * (1.0 - noise_penalty)

    overall = weighted_fc + weighted_ps + weighted_noise
    percent = int(round(overall * 100))

    # Points-based: net pattern points minus noise instances
    net_points = pattern_points - (noise_count * 0.5)

    grade = "F"
    for threshold, letter in GRADE_THRESHOLDS:
        if percent >= threshold:
            grade = letter
            break

    return {
        "overall_score": round(overall, 4),
        "overall_percent": percent,
        "grade": grade,
        "points": round(net_points, 2),
        "positive_points": round(positive_points, 2),
        "negative_points": round(negative_points, 2),
        "components": {
            "file_coverage": {
                "score": round(file_coverage, 4),
                "weight": WEIGHT_FILE_COVERAGE,
                "weighted": round(weighted_fc, 4),
            },
            "pattern_score": {
                "score": round(pattern_score, 4),
                "weight": WEIGHT_PATTERN_SCORE,
                "weighted": round(weighted_ps, 4),
                "points": round(pattern_points, 2),
            },
            "noise_penalty": {
                "raw_penalty": round(noise_penalty, 4),
                "weight": WEIGHT_NOISE,
                "weighted": round(weighted_noise, 4),
            },
        },
    }


def generate_recommendations(
    pattern_results: list[dict[str, Any]],
    noise_instances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate actionable recommendations prioritized by impact."""
    recommendations: list[dict[str, Any]] = []

    # Pattern-based recommendations
    for result in pattern_results:
        status = result.get("status", "not_applicable")
        if status == "missing":
            recommendations.append({
                "priority": "high",
                "message": f"Missing migration pattern: {result['name']} — "
                f"this {result.get('complexity', 'moderate')}-complexity pattern "
                f"was not applied in {len(result.get('files', []))} file(s)",
                "pattern_id": result["pattern_id"],
            })
        elif status == "incorrect":
            recommendations.append({
                "priority": "high",
                "message": f"Incorrect migration: {result['name']} — "
                f"pattern was applied incorrectly",
                "pattern_id": result["pattern_id"],
            })

    # Noise-based recommendations
    artifact_count = sum(1 for n in noise_instances if n["type"] == "artifact")
    placeholder_count = sum(1 for n in noise_instances if n["type"] == "placeholder_token")
    formatting_count = sum(1 for n in noise_instances if n["type"] == "formatting_only")
    unnecessary_count = sum(1 for n in noise_instances if n["type"] == "unnecessary_change")

    if artifact_count > 0:
        recommendations.append({
            "priority": "medium",
            "message": f"Remove {artifact_count} debug artifact(s) "
            f"(console.log, debugger, @ts-ignore)",
        })
    if placeholder_count > 0:
        recommendations.append({
            "priority": "medium",
            "message": f"Resolve {placeholder_count} placeholder token(s) "
            f"(FIXME, TODO, HACK, etc.)",
        })
    if formatting_count > 0:
        recommendations.append({
            "priority": "low",
            "message": f"{formatting_count} file(s) have formatting-only changes "
            f"— consider reverting unnecessary whitespace modifications",
        })
    if unnecessary_count > 0:
        recommendations.append({
            "priority": "low",
            "message": f"{unnecessary_count} file(s) added in candidate "
            f"but not present in reference",
        })

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: priority_order.get(r.get("priority", "low"), 2))

    return recommendations


def build_scoring_results(
    target: str | None,
    file_coverage_data: dict[str, Any],
    pattern_score_data: dict[str, Any],
    noise_penalty_data: dict[str, Any],
    pattern_results: list[dict[str, Any]],
    noise_instances: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    comparison_data: dict[str, Any],
    dir_a: str = "",
    dir_b: str = "",
    label: str | None = None,
) -> dict[str, Any]:
    """Build the final scoring-results.json structure."""
    fc_score = file_coverage_data["score"]
    ps_score = pattern_score_data["score"]
    np_penalty = noise_penalty_data["capped_penalty"]

    final = compute_final_score(
        fc_score, ps_score, np_penalty,
        pattern_points=pattern_score_data.get("points", 0.0),
        positive_points=pattern_score_data.get("positive_points", 0.0),
        negative_points=pattern_score_data.get("negative_points", 0.0),
        noise_count=noise_penalty_data.get("instance_count", 0),
    )

    # Augment components with extra details
    final["components"]["file_coverage"]["matched"] = file_coverage_data["matched"]
    final["components"]["file_coverage"]["total"] = file_coverage_data["total"]
    final["components"]["pattern_score"]["by_complexity"] = pattern_score_data.get(
        "by_complexity", {}
    )
    final["components"]["noise_penalty"]["instance_count"] = noise_penalty_data[
        "instance_count"
    ]

    # Build per-file results
    files = comparison_data.get("files", {})
    modified: list[dict[str, Any]] = files.get("modified", [])
    file_results: list[dict[str, Any]] = []
    for f in modified:
        path = f.get("path", "")
        if _is_excluded(path):
            continue

        # Gather pattern statuses for this file
        pattern_statuses: dict[str, str] = {}
        for pr in pattern_results:
            for detail in pr.get("details", []):
                if detail.get("file") == path:
                    pattern_statuses[pr["pattern_id"]] = detail["status"]

        # Count noise for this file
        file_noise = [n for n in noise_instances if n.get("file") == path]
        file_noise_penalty = sum(n.get("penalty", 0) for n in file_noise)

        file_results.append({
            "path": path,
            "pattern_statuses": pattern_statuses,
            "noise_count": len(file_noise),
            "noise_penalty": round(file_noise_penalty, 4),
        })

    target_patterns_loaded = len(pattern_results) if target else 0

    return {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target": target,
            "target_patterns_loaded": target_patterns_loaded,
            "scoring_version": "1.0",
            "dir_a": str(Path(dir_a).resolve()) if dir_a else "",
            "dir_b": str(Path(dir_b).resolve()) if dir_b else "",
            "label": label,
        },
        "score": final,
        "pattern_results": pattern_results,
        "noise_instances": noise_instances,
        "file_results": file_results,
        "recommendations": recommendations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score migration quality by comparing candidate against reference"
    )
    parser.add_argument(
        "--comparison-data",
        required=True,
        help="Path to comparison-data.json",
    )
    parser.add_argument("--dir-a", required=True, help="Path to reference directory")
    parser.add_argument("--dir-b", required=True, help="Path to candidate directory")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write scoring-results.json",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Migration target for target-specific patterns (e.g., 'patternfly')",
    )
    parser.add_argument(
        "--targets-dir",
        default=None,
        help="Directory containing target pattern files (default: ../targets relative to this script)",
    )
    parser.add_argument(
        "--before-migration",
        default=None,
        help="Path to the source codebase before any migration was applied",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Semantic label for this scoring run (e.g., 'golden-vs-ai-agent')",
    )

    args = parser.parse_args()

    # Load comparison data
    comp_data_path = Path(args.comparison_data)
    if not comp_data_path.exists():
        print(
            f"Error: comparison-data.json not found: {comp_data_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(comp_data_path, "r", encoding="utf-8") as f:
        comparison_data: dict[str, Any] = json.load(f)

    # Resolve targets directory
    if args.targets_dir:
        targets_dir = Path(args.targets_dir)
    else:
        targets_dir = Path(__file__).parent.parent / "targets"

    # Step 1: File coverage
    file_coverage_data = compute_file_coverage(comparison_data)
    print(
        f"File coverage: {file_coverage_data['matched']}/{file_coverage_data['total']} "
        f"({file_coverage_data['score']:.1%})"
    )

    # Step 2: Pattern scoring
    pattern_results: list[dict[str, Any]] = []
    if args.target:
        patterns = load_target_patterns(args.target, targets_dir)
        if patterns:
            print(f"Loaded {len(patterns)} patterns for target '{args.target}'")
            pattern_results = run_pattern_detectors(
                patterns, comparison_data, args.dir_a, args.dir_b,
                before_migration_dir=args.before_migration,
            )
            pattern_score_data = compute_pattern_score(pattern_results)
        else:
            print(f"No patterns loaded for target '{args.target}', using generic scoring")
            pattern_score_data = compute_generic_pattern_score(comparison_data)
    else:
        print("No target specified, using generic pattern scoring")
        pattern_score_data = compute_generic_pattern_score(comparison_data)

    pts = pattern_score_data.get("points", 0)
    pos = pattern_score_data.get("positive_points", 0)
    neg = pattern_score_data.get("negative_points", 0)
    print(f"Pattern score: {pattern_score_data['score']:.1%} | Points: {pts:+.1f} (+{pos:.1f} / {neg:.1f})")

    # Step 3: Noise detection
    noise_instances = detect_noise(
        comparison_data, args.dir_a, args.dir_b,
        pattern_results=pattern_results,
    )
    noise_penalty_data = compute_noise_penalty(noise_instances)
    print(
        f"Noise penalty: {noise_penalty_data['capped_penalty']:.1%} "
        f"({noise_penalty_data['instance_count']} instances)"
    )

    # Step 4: Recommendations
    recommendations = generate_recommendations(pattern_results, noise_instances)

    # Step 5: Build results
    results = build_scoring_results(
        target=args.target,
        file_coverage_data=file_coverage_data,
        pattern_score_data=pattern_score_data,
        noise_penalty_data=noise_penalty_data,
        pattern_results=pattern_results,
        noise_instances=noise_instances,
        recommendations=recommendations,
        comparison_data=comparison_data,
        dir_a=args.dir_a,
        dir_b=args.dir_b,
        label=args.label,
    )

    # Compute and display final score
    score = results["score"]
    print(
        f"\nOverall: {score['overall_percent']}% (Grade {score['grade']}) | "
        f"Points: {score['points']:+.1f} (+{score['positive_points']:.1f} / {score['negative_points']:.1f})"
    )

    # Write output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "scoring-results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(str(output_path))


if __name__ == "__main__":
    main()
