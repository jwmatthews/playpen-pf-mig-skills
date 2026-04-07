#!/usr/bin/env python3
"""
Execute diffs for each modified file in a file manifest.

Uses GumTree AST diffing when available, with text diff fallback.
Outputs per-file diff results to diff-results.json in the workspace directory.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Extensions GumTree supports via its bundled generators.
# Based on `gumtree list GENERATORS` output from the official Docker image.
# Note: .tsx and .jsx are NOT supported — no generator registered for those extensions.
GUMTREE_LANGUAGES: dict[str, str] = {
    ".ts": "ts-treesitter-ng",
    ".js": "js-treesitter-ng",
    ".py": "python-treesitter-ng",
    ".java": "java-jdt",
    ".css": "css-phcss",
    ".go": "go-treesitter-ng",
    ".rs": "rust-treesitter-ng",
    ".rb": "ruby-treesitter-ng",
    ".c": "c-treesitter-ng",
    ".cpp": "cpp-treesitter-ng",
    ".h": "c-treesitter-ng",
    ".hpp": "cpp-treesitter-ng",
    ".kt": "kotlin-treesitter-ng",
    ".swift": "swift-treesitter-ng",
    ".php": "php-treesitter-ng",
    ".ml": "ocaml-treesitter-ng",
    ".yaml": "yaml-snakeyaml",
    ".yml": "yaml-snakeyaml",
    ".xml": "xml-jsoup",
}

MAX_AST_DIFF_SIZE: int = 1 * 1024 * 1024  # 1MB
DIFF_TIMEOUT: int = 30  # seconds


def check_gumtree_native() -> dict[str, str] | None:
    """Check if GumTree is available as a native binary."""
    path = shutil.which("gumtree")
    if not path:
        return None
    try:
        result = subprocess.run(
            ["gumtree", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
        return {"method": "native", "version": version, "path": path}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def check_gumtree_container(runtime: str) -> dict[str, str] | None:
    """Check if GumTree is available via a container runtime (docker or podman)."""
    bin_path = shutil.which(runtime)
    if not bin_path:
        return None
    try:
        result = subprocess.run(
            [runtime, "image", "inspect", "gumtreediff/gumtree"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return {"method": runtime, "version": f"{runtime}-image", "path": bin_path}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def check_gumtree() -> dict[str, Any]:
    """Probe for GumTree availability. Returns JSON result.

    Checks in order: native binary, podman, docker.
    """
    native = check_gumtree_native()
    if native:
        return {"available": True, **native}

    for runtime in ("podman", "docker"):
        container = check_gumtree_container(runtime)
        if container:
            return {"available": True, **container}

    return {"available": False, "method": "none", "version": None}


def run_gumtree_native(file_a: str | Path, file_b: str | Path) -> dict[str, Any]:
    """Run GumTree textdiff via native binary."""
    proc = subprocess.run(
        ["gumtree", "textdiff", "-f", "JSON", str(file_a), str(file_b)],
        capture_output=True,
        text=True,
        timeout=DIFF_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"GumTree failed: {proc.stderr.strip()}")
    stdout = proc.stdout.strip()
    if not stdout:
        err = proc.stderr.strip()
        raise RuntimeError(f"GumTree produced no output: {err}")
    parsed: dict[str, Any] = json.loads(stdout)
    return parsed


def run_gumtree_container(
    file_a: str | Path, file_b: str | Path, runtime: str = "podman"
) -> dict[str, Any]:
    """Run GumTree textdiff via a container runtime (podman or docker)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src_a = Path(tmpdir) / "a" / Path(file_a).name
        src_b = Path(tmpdir) / "b" / Path(file_b).name
        src_a.parent.mkdir()
        src_b.parent.mkdir()
        shutil.copy2(file_a, src_a)
        shutil.copy2(file_b, src_b)

        container_a = f"/data/a/{Path(file_a).name}"
        container_b = f"/data/b/{Path(file_b).name}"

        proc = subprocess.run(
            [
                runtime,
                "run",
                "--rm",
                "-v",
                f"{tmpdir}:/data",
                "gumtreediff/gumtree",
                "textdiff",
                "-f",
                "JSON",
                container_a,
                container_b,
            ],
            capture_output=True,
            text=True,
            timeout=DIFF_TIMEOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"GumTree {runtime} failed: {proc.stderr.strip()}")
        # GumTree may exit 0 but print errors to stderr with no stdout
        stdout = proc.stdout.strip()
        if not stdout:
            err = proc.stderr.strip()
            raise RuntimeError(f"GumTree {runtime} produced no output: {err}")
        parsed: dict[str, Any] = json.loads(stdout)
        return parsed


def run_text_diff(file_a: str | Path, file_b: str | Path) -> dict[str, Any]:
    """Run a text-based unified diff using difflib."""
    try:
        with open(file_a, "r", encoding="utf-8", errors="replace") as f:
            lines_a = [line.rstrip("\n") for line in f.readlines()]
        with open(file_b, "r", encoding="utf-8", errors="replace") as f:
            lines_b = [line.rstrip("\n") for line in f.readlines()]
    except (OSError, IOError) as e:
        raise RuntimeError(f"Cannot read files: {e}")

    diff = list(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=str(file_a),
            tofile=str(file_b),
            lineterm="",
        )
    )

    lines_added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    lines_removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

    return {
        "diff_text": "\n".join(diff),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def diff_single_file(
    file_info: dict[str, Any],
    dir_a: str,
    dir_b: str,
    gumtree_info: dict[str, Any],
    no_gumtree: bool,
) -> dict[str, Any]:
    """Diff a single modified file. Returns the result dict."""
    rel_path: str = file_info["path"]
    path_a = Path(dir_a) / rel_path
    path_b = Path(dir_b) / rel_path
    ext = Path(rel_path).suffix.lower()

    result: dict[str, Any] = {
        "path": rel_path,
        "diff_method": None,
        "text_diff": None,
        "gumtree_actions": None,
        "stats": {
            "lines_added": 0,
            "lines_removed": 0,
            "ast_actions": None,
        },
        "error": None,
    }

    # Skip binary files
    if file_info.get("binary"):
        result["diff_method"] = "binary_skip"
        return result

    # Always do text diff (it's the fallback and provides line stats)
    try:
        text_result = run_text_diff(path_a, path_b)
        result["text_diff"] = text_result["diff_text"]
        result["stats"]["lines_added"] = text_result["lines_added"]
        result["stats"]["lines_removed"] = text_result["lines_removed"]
        result["diff_method"] = "text"
    except Exception as e:
        result["error"] = f"Text diff failed: {e}"
        result["diff_method"] = "error"
        return result

    # Try GumTree if available and applicable
    use_gumtree = (
        not no_gumtree
        and gumtree_info.get("available")
        and ext in GUMTREE_LANGUAGES
        and file_info.get("size_a", 0) <= MAX_AST_DIFF_SIZE
        and file_info.get("size_b", 0) <= MAX_AST_DIFF_SIZE
    )

    if use_gumtree:
        try:
            method = gumtree_info["method"]
            if method == "native":
                gt_result = run_gumtree_native(path_a, path_b)
            elif method in ("podman", "docker"):
                gt_result = run_gumtree_container(path_a, path_b, runtime=method)
            else:
                gt_result = None

            if gt_result is not None:
                result["gumtree_actions"] = gt_result
                result["diff_method"] = "gumtree"

                # Count AST actions by type
                actions: list[dict[str, Any]] = (
                    gt_result if isinstance(gt_result, list) else gt_result.get("actions", [])
                )
                action_counts: dict[str, int] = {}
                for action in actions:
                    atype = action.get("action", "unknown")
                    action_counts[atype] = action_counts.get(atype, 0) + 1
                result["stats"]["ast_actions"] = action_counts
        except Exception as e:
            # GumTree failed for this file — keep text diff, record error
            result["error"] = f"GumTree fallback to text: {e}"

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute diffs for modified files in a manifest"
    )
    parser.add_argument(
        "--check-gumtree",
        action="store_true",
        help="Check GumTree availability and exit",
    )
    parser.add_argument("--manifest", help="Path to file-manifest.json")
    parser.add_argument("--dir-a", help="Path to directory A")
    parser.add_argument("--dir-b", help="Path to directory B")
    parser.add_argument(
        "--output-dir",
        help="Directory to write diff-results.json (default: same as manifest)",
    )
    parser.add_argument(
        "--no-gumtree",
        action="store_true",
        help="Skip all GumTree attempts, use text diff only",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 8)",
    )

    args = parser.parse_args()

    # Check-gumtree mode
    if args.check_gumtree:
        result = check_gumtree()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["available"] else 1)

    # Normal diff mode — validate required args
    if not args.manifest or not args.dir_a or not args.dir_b:
        parser.error("--manifest, --dir-a, and --dir-b are required for diffing")

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    modified_files: list[dict[str, Any]] = manifest.get("modified", [])
    if not modified_files:
        print("No modified files to diff.")
        empty_result: dict[str, Any] = {
            "files": [],
            "errors": [],
            "summary": {"total": 0, "gumtree": 0, "text": 0, "failed": 0},
        }
        output_dir = Path(args.output_dir) if args.output_dir else manifest_path.parent
        output_path = output_dir / "diff-results.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(empty_result, f, indent=2)
        print(str(output_path))
        sys.exit(0)

    # Check GumTree availability
    if args.no_gumtree:
        gumtree_info: dict[str, Any] = {"available": False, "method": "none", "version": None}
    else:
        gumtree_info = check_gumtree()

    # Run diffs in parallel
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    gumtree_count = 0
    text_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures: dict[Any, str] = {}
        for file_info in modified_files:
            future = executor.submit(
                diff_single_file,
                file_info,
                args.dir_a,
                args.dir_b,
                gumtree_info,
                args.no_gumtree,
            )
            futures[future] = file_info["path"]

        for future in as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
                results.append(result)
                if result["diff_method"] == "gumtree":
                    gumtree_count += 1
                elif result["diff_method"] == "text":
                    text_count += 1
                elif result["diff_method"] == "error":
                    failed_count += 1
                if result.get("error"):
                    errors.append({"path": path, "error": result["error"]})
            except Exception as e:
                failed_count += 1
                errors.append({"path": path, "error": str(e)})
                results.append({
                    "path": path,
                    "diff_method": "error",
                    "text_diff": None,
                    "gumtree_actions": None,
                    "stats": {"lines_added": 0, "lines_removed": 0, "ast_actions": None},
                    "error": str(e),
                })

    # Sort results by path for deterministic output
    results.sort(key=lambda r: r["path"])

    output: dict[str, Any] = {
        "gumtree": gumtree_info,
        "files": results,
        "errors": errors,
        "summary": {
            "total": len(modified_files),
            "gumtree": gumtree_count,
            "text": text_count,
            "binary_skip": sum(1 for r in results if r["diff_method"] == "binary_skip"),
            "failed": failed_count,
        },
    }

    output_dir = Path(args.output_dir) if args.output_dir else manifest_path.parent
    output_path = output_dir / "diff-results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(str(output_path))


if __name__ == "__main__":
    main()
