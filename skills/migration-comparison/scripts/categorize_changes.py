#!/usr/bin/env python3
"""
Read per-file diff results and the file manifest, assign change categories,
and produce comparison-data.json.

Categories:
  - structural: AST moves, renames, reordering of code blocks
  - semantic: value changes, logic changes (AST updates)
  - api_changes: import changes, module references
  - cosmetic: whitespace-only, formatting-only changes
  - additive: new code inserted (AST inserts, text additions)
  - subtractive: code removed (AST deletes, text removals)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def categorize_gumtree(actions: dict[str, Any] | list[dict[str, Any]] | None) -> set[str]:
    """Categorize based on GumTree AST action types."""
    categories: set[str] = set()
    if not actions:
        return categories

    action_list: list[dict[str, Any]] = (
        actions if isinstance(actions, list) else actions.get("actions", [])
    )
    for action in action_list:
        atype = action.get("action", "").lower()
        if atype in ("move", "move-tree"):
            categories.add("structural")
        elif atype in ("update",):
            categories.add("semantic")
        elif atype in ("insert", "insert-tree", "insert-node"):
            categories.add("additive")
        elif atype in ("delete", "delete-tree", "delete-node"):
            categories.add("subtractive")

    return categories


def categorize_text_diff(diff_text: str | None) -> set[str]:
    """Categorize based on text diff heuristics."""
    categories: set[str] = set()
    if not diff_text:
        return categories

    lines = diff_text.split("\n")
    added_lines: list[str] = []
    removed_lines: list[str] = []

    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])

    if not added_lines and not removed_lines:
        return categories

    # Check for whitespace-only changes
    added_stripped = [l.strip() for l in added_lines if l.strip()]
    removed_stripped = [l.strip() for l in removed_lines if l.strip()]
    if not added_stripped and not removed_stripped:
        categories.add("cosmetic")
        return categories

    # Check if only whitespace differs (after stripping, content is same)
    if sorted(added_stripped) == sorted(removed_stripped):
        categories.add("cosmetic")
        return categories

    # Check for import/require changes -> API
    import_pattern = re.compile(
        r"^\s*(import\s|from\s|require\s*\(|export\s)", re.IGNORECASE
    )
    import_adds = [l for l in added_lines if import_pattern.match(l)]
    import_removes = [l for l in removed_lines if import_pattern.match(l)]
    non_import_adds = [l for l in added_lines if not import_pattern.match(l) and l.strip()]
    non_import_removes = [l for l in removed_lines if not import_pattern.match(l) and l.strip()]

    if import_adds or import_removes:
        categories.add("api_changes")

    # If only imports changed, that's all
    if not non_import_adds and not non_import_removes:
        return categories

    # Pure additions (non-import content added, no non-import content removed)
    if non_import_adds and not non_import_removes:
        categories.add("additive")

    # Pure removals (non-import content removed, no non-import content added)
    if non_import_removes and not non_import_adds:
        categories.add("subtractive")

    # Mixed changes -> semantic
    if added_stripped and removed_stripped:
        categories.add("semantic")

    # If no category assigned yet, default to semantic
    if not categories:
        categories.add("semantic")

    return categories


def build_comparison_data(
    manifest: dict[str, Any],
    diff_results: dict[str, Any],
    label_a: str,
    label_b: str,
    dir_a: str,
    dir_b: str,
    gumtree_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the full comparison-data.json structure."""
    timestamp = datetime.now(timezone.utc).isoformat()

    total_lines_added = 0
    total_lines_removed = 0
    ast_diffs = 0
    text_diffs = 0

    modified_with_categories: list[dict[str, Any]] = []
    diff_by_path: dict[str, dict[str, Any]] = {
        f["path"]: f for f in diff_results.get("files", [])
    }

    for file_info in manifest.get("modified", []):
        path: str = file_info["path"]
        diff_info = diff_by_path.get(path, {})

        stats = diff_info.get("stats", {})
        lines_added: int = stats.get("lines_added", 0)
        lines_removed: int = stats.get("lines_removed", 0)
        total_lines_added += lines_added
        total_lines_removed += lines_removed

        diff_method: str = diff_info.get("diff_method", "text")
        if diff_method == "gumtree":
            ast_diffs += 1
            categories = categorize_gumtree(diff_info.get("gumtree_actions"))
            # Also apply text heuristics for API detection
            text_cats = categorize_text_diff(diff_info.get("text_diff", ""))
            if "api_changes" in text_cats:
                categories.add("api_changes")
            if "cosmetic" in text_cats and not categories:
                categories.add("cosmetic")
        elif diff_method == "text":
            text_diffs += 1
            categories = categorize_text_diff(diff_info.get("text_diff", ""))
        else:
            categories = set()

        cat_list = sorted(categories) if categories else ["semantic"]

        modified_with_categories.append({
            "path": path,
            "diff_method": diff_method,
            "categories": cat_list,
            "stats": {
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "ast_actions": stats.get("ast_actions"),
            },
            "text_diff": diff_info.get("text_diff", ""),
            "gumtree_actions": diff_info.get("gumtree_actions"),
            "error": diff_info.get("error"),
        })

    # Build category index
    all_categories = [
        "structural",
        "semantic",
        "api_changes",
        "cosmetic",
        "additive",
        "subtractive",
    ]
    categories_index: dict[str, dict[str, Any]] = {}
    for cat in all_categories:
        files_in_cat = [
            f["path"]
            for f in modified_with_categories
            if cat in f["categories"]
        ]
        categories_index[cat] = {
            "count": len(files_in_cat),
            "files": files_in_cat,
        }

    errors: list[dict[str, str]] = diff_results.get("errors", [])

    gumtree_method = "none"
    if gumtree_info:
        gumtree_method = gumtree_info.get("method", "none")

    data: dict[str, Any] = {
        "metadata": {
            "timestamp": timestamp,
            "repo_a": {"path": str(dir_a), "label": label_a},
            "repo_b": {"path": str(dir_b), "label": label_b},
            "gumtree_available": gumtree_info.get("available", False) if gumtree_info else False,
            "gumtree_method": gumtree_method,
        },
        "summary": {
            "total_files_compared": manifest["stats"]["added_count"]
            + manifest["stats"]["removed_count"]
            + manifest["stats"]["modified_count"]
            + manifest["stats"]["identical_count"],
            "files_added": manifest["stats"]["added_count"],
            "files_removed": manifest["stats"]["removed_count"],
            "files_modified": manifest["stats"]["modified_count"],
            "files_identical": manifest["stats"]["identical_count"],
            "ast_diffs_performed": ast_diffs,
            "text_diffs_performed": text_diffs,
            "total_lines_added": total_lines_added,
            "total_lines_removed": total_lines_removed,
        },
        "categories": categories_index,
        "files": {
            "added": manifest.get("added", []),
            "removed": manifest.get("removed", []),
            "modified": modified_with_categories,
        },
        "annotations": [],
        "errors": errors,
    }

    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Categorize changes from diff results and file manifest"
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to file-manifest.json",
    )
    parser.add_argument(
        "--diff-results",
        required=True,
        help="Path to diff-results.json",
    )
    parser.add_argument(
        "--dir-a",
        required=True,
        help="Path to directory A",
    )
    parser.add_argument(
        "--dir-b",
        required=True,
        help="Path to directory B",
    )
    parser.add_argument(
        "--label-a",
        default="Reference A",
        help="Label for reference A",
    )
    parser.add_argument(
        "--label-b",
        default="Reference B",
        help="Label for reference B",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to write comparison-data.json (default: same as manifest)",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    diff_path = Path(args.diff_results)

    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)
    if not diff_path.exists():
        print(f"Error: Diff results not found: {diff_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest: dict[str, Any] = json.load(f)
    with open(diff_path, "r", encoding="utf-8") as f:
        diff_results: dict[str, Any] = json.load(f)

    gumtree_info: dict[str, Any] | None = diff_results.get("gumtree")

    data = build_comparison_data(
        manifest,
        diff_results,
        args.label_a,
        args.label_b,
        args.dir_a,
        args.dir_b,
        gumtree_info,
    )

    output_dir = Path(args.output_dir) if args.output_dir else manifest_path.parent
    output_path = output_dir / "comparison-data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(str(output_path))


if __name__ == "__main__":
    main()
