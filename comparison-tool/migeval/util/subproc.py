"""Safe subprocess execution with timeouts."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class RunResult:
    """Result of a subprocess execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_command(
    cmd: str,
    cwd: str | None = None,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> RunResult:
    """Run a shell command and capture output.

    Args:
        cmd: Shell command to run.
        cwd: Working directory.
        timeout: Timeout in seconds (default 5 minutes).
        env: Optional environment variables.

    Returns:
        RunResult with exit code, stdout, stderr, and timeout flag.
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return RunResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s: {cmd}",
            timed_out=True,
        )
