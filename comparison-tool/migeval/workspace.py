"""Workspace management: git worktrees and temp directories."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def checkout_ref(repo: Path, ref: str, workdir: Path) -> Path:
    """Check out a git ref into a worktree under workdir.

    Returns the path to the worktree.
    """
    worktree_path = workdir / f"worktree-{ref.replace('/', '_')}"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), ref],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    return worktree_path


def cleanup_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove a git worktree."""
    subprocess.run(
        ["git", "worktree", "remove", str(worktree_path), "--force"],
        cwd=str(repo),
        capture_output=True,
    )


def make_temp_dir(prefix: str = "migeval-") -> Path:
    """Create a temporary directory that persists until explicitly cleaned up."""
    return Path(tempfile.mkdtemp(prefix=prefix))


def copy_to_temp(source: Path, prefix: str = "migeval-") -> Path:
    """Copy a directory to a temporary location."""
    tmp = make_temp_dir(prefix)
    dest = tmp / source.name
    shutil.copytree(source, dest, symlinks=True)
    return dest
