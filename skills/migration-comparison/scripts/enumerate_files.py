#!/usr/bin/env python3
"""
Walk two directory trees and build a file manifest classifying files as
added, removed, modified, or identical.

Outputs file-manifest.json to the workspace directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

SKIP_DIRS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".next",
    ".nuxt",
    "dist",
    "build",
    ".cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    ".mypy_cache",
    ".pytest_cache",
    "coverage",
    ".nyc_output",
    ".turbo",
}

LANGUAGE_MAP: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".html": "html",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".md": "markdown",
    ".txt": "text",
    ".sh": "shell",
    ".bash": "shell",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "config",
    ".svg": "svg",
}


def sha256_file(path: str | Path) -> str | None:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


def is_binary(path: str | Path) -> bool:
    """Heuristic binary detection: check first 8KB for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except (OSError, IOError):
        return True


def walk_tree(root: str | Path) -> dict[str, dict[str, Any]]:
    """Walk a directory tree, returning a dict of relative_path -> info."""
    root = Path(root).resolve()
    files: dict[str, dict[str, Any]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            full = Path(dirpath) / fname
            rel = str(full.relative_to(root))
            ext = full.suffix.lower()
            binary = is_binary(full)
            files[rel] = {
                "absolute": str(full),
                "language": LANGUAGE_MAP.get(ext, "other"),
                "extension": ext,
                "binary": binary,
                "size": full.stat().st_size,
                "hash": sha256_file(full),
            }
    return files


def build_manifest(
    tree_a: dict[str, dict[str, Any]],
    tree_b: dict[str, dict[str, Any]],
    label_a: str,
    label_b: str,
) -> dict[str, Any]:
    """Compare two file trees and build the manifest."""
    all_paths = sorted(set(tree_a.keys()) | set(tree_b.keys()))

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    identical: list[dict[str, Any]] = []

    for path in all_paths:
        in_a = path in tree_a
        in_b = path in tree_b

        if in_a and not in_b:
            removed.append({
                "path": path,
                "language": tree_a[path]["language"],
                "binary": tree_a[path]["binary"],
                "size": tree_a[path]["size"],
            })
        elif in_b and not in_a:
            added.append({
                "path": path,
                "language": tree_b[path]["language"],
                "binary": tree_b[path]["binary"],
                "size": tree_b[path]["size"],
            })
        else:
            info_a = tree_a[path]
            info_b = tree_b[path]
            if info_a["hash"] == info_b["hash"]:
                identical.append({
                    "path": path,
                    "language": info_a["language"],
                    "binary": info_a["binary"],
                })
            else:
                modified.append({
                    "path": path,
                    "language": info_a["language"],
                    "binary": info_a["binary"] or info_b["binary"],
                    "size_a": info_a["size"],
                    "size_b": info_b["size"],
                })

    return {
        "repo_a": {"label": label_a},
        "repo_b": {"label": label_b},
        "total_files": len(all_paths),
        "added": added,
        "removed": removed,
        "modified": modified,
        "identical": identical,
        "stats": {
            "added_count": len(added),
            "removed_count": len(removed),
            "modified_count": len(modified),
            "identical_count": len(identical),
            "overlapping_count": len(modified) + len(identical),
        },
    }


def check_only(dir_a: str | Path, dir_b: str | Path) -> dict[str, int]:
    """Quick overlap check without building full manifest."""
    tree_a = walk_tree(dir_a)
    tree_b = walk_tree(dir_b)
    paths_a = set(tree_a.keys())
    paths_b = set(tree_b.keys())
    overlap = paths_a & paths_b
    result: dict[str, int] = {
        "files_in_a": len(paths_a),
        "files_in_b": len(paths_b),
        "overlapping": len(overlap),
        "only_in_a": len(paths_a - paths_b),
        "only_in_b": len(paths_b - paths_a),
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk two directory trees and build a file manifest"
    )
    parser.add_argument("dir_a", help="Path to reference directory A")
    parser.add_argument("dir_b", help="Path to reference directory B")
    parser.add_argument(
        "--label-a", default="Reference A", help="Label for directory A"
    )
    parser.add_argument(
        "--label-b", default="Reference B", help="Label for directory B"
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to write file-manifest.json (default: current directory)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report overlap stats, don't build full manifest",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Glob patterns to filter files (can be specified multiple times)",
    )

    args = parser.parse_args()

    dir_a = Path(args.dir_a)
    dir_b = Path(args.dir_b)

    if not dir_a.is_dir():
        print(f"Error: Directory not found: {dir_a}", file=sys.stderr)
        sys.exit(1)
    if not dir_b.is_dir():
        print(f"Error: Directory not found: {dir_b}", file=sys.stderr)
        sys.exit(1)

    if args.check_only:
        result = check_only(dir_a, dir_b)
        sys.exit(0 if result["overlapping"] > 0 else 2)

    tree_a = walk_tree(dir_a)
    tree_b = walk_tree(dir_b)

    if args.filter:
        import fnmatch

        def matches_any(path: str, patterns: list[str]) -> bool:
            return any(fnmatch.fnmatch(path, p) for p in patterns)

        tree_a = {p: v for p, v in tree_a.items() if matches_any(p, args.filter)}
        tree_b = {p: v for p, v in tree_b.items() if matches_any(p, args.filter)}

    manifest = build_manifest(tree_a, tree_b, args.label_a, args.label_b)

    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
    output_path = output_dir / "file-manifest.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(str(output_path))


if __name__ == "__main__":
    main()
