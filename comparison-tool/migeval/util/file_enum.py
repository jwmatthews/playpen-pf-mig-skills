"""File enumeration utilities."""

from __future__ import annotations

from pathlib import Path

# Directories to always skip
SKIP_DIRS = frozenset({
    "node_modules",
    ".git",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".next",
    ".nuxt",
})


def enumerate_files(
    root: Path,
    extensions: list[str] | None = None,
) -> list[Path]:
    """Enumerate source files under root, skipping common non-source directories.

    Args:
        root: Root directory to scan.
        extensions: If provided, only return files matching these extensions
                   (e.g., [".tsx", ".ts"]). Include the leading dot.

    Returns:
        Sorted list of matching file paths.
    """
    results: list[Path] = []
    ext_set = set(extensions) if extensions else None

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        # Skip files in excluded directories
        if any(part in SKIP_DIRS for part in path.parts):
            continue

        if ext_set and path.suffix not in ext_set:
            continue

        results.append(path)

    results.sort()
    return results
