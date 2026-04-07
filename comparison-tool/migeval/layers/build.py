"""Build evaluation layer.

Runs install + build commands and parses error output.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from migeval.config import merge_configs
from migeval.models import (
    Issue,
    LayerContext,
    LayerName,
    LayerResult,
    ProjectConfig,
    TargetConfig,
    make_issue_id,
)
from migeval.prompts import load_prompt
from migeval.util.agent import run_agent_query
from migeval.util.llm import render_template
from migeval.util.subproc import RunResult, run_command


class BuildLayer:
    """Runs install + build and captures errors."""

    name: LayerName = "build"

    def can_run(
        self,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> tuple[bool, str]:
        """Check if build config is available."""
        merged = merge_configs(target, project)
        if merged.build is None:
            return False, "No build config in target or project"
        return True, ""

    def evaluate(
        self,
        path: Path,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> LayerResult:
        """Run install + build and parse errors."""
        start = time.monotonic()
        merged = merge_configs(target, project)
        assert merged.build is not None  # guaranteed by can_run

        issues: list[Issue] = []
        metadata: dict[str, Any] = {}

        # Install
        install_result = run_command(
            merged.build.install_cmd, cwd=str(path), timeout=300
        )
        metadata["install_exit_code"] = install_result.exit_code
        if install_result.exit_code != 0:
            metadata["install_stderr"] = install_result.stderr[:5000]

        # Build (even if install had warnings, try building)
        build_result = run_command(
            merged.build.build_cmd, cwd=str(path), timeout=300
        )
        metadata["build_exit_code"] = build_result.exit_code
        metadata["build_stdout"] = build_result.stdout[:10000]
        metadata["build_stderr"] = build_result.stderr[:10000]

        build_passed = build_result.exit_code == 0

        if not build_passed:
            # Parse build errors
            combined_output = build_result.stdout + "\n" + build_result.stderr
            parsed_errors = _parse_build_errors(combined_output)
            for err in parsed_errors:
                issues.append(
                    Issue(
                        id=make_issue_id(
                            "build_error",
                            err.get("file", ""),
                            err.get("code", ""),
                        ),
                        source="build_error",
                        severity="high",
                        file=err.get("file"),
                        line=err.get("line"),
                        title=err.get("title", "Build error"),
                        detail=err.get("message", ""),
                        evidence=err.get("evidence", ""),
                    )
                )

            # If no structured errors parsed, create one generic error
            if not issues:
                issues.append(
                    Issue(
                        id=make_issue_id("build_error", "generic", ""),
                        source="build_error",
                        severity="high",
                        title="Build failed",
                        detail=(
                            f"Build command failed with exit code"
                            f" {build_result.exit_code}"
                        ),
                        evidence=combined_output[:2000],
                    )
                )

            # LLM error analysis via Agent SDK (best-effort)
            with contextlib.suppress(Exception):
                _agent_analyze_build(target, merged, build_result, metadata)

        elapsed = time.monotonic() - start
        return LayerResult(
            layer="build",
            success=True,
            duration_seconds=round(elapsed, 2),
            issues=issues,
            metadata=metadata,
        )


def _parse_build_errors(output: str) -> list[dict[str, Any]]:
    """Parse TypeScript / webpack / vite build errors from output."""
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()

    # TypeScript errors: src/foo.tsx(42,5): error TS2322: ...
    ts_pattern = re.compile(
        r"([^\s(]+)\((\d+),\d+\):\s*error\s+(TS\d+):\s*(.*)"
    )
    for match in ts_pattern.finditer(output):
        file, line, code, message = match.groups()
        key = f"{file}:{code}"
        if key not in seen:
            seen.add(key)
            errors.append({
                "file": file,
                "line": int(line),
                "code": code,
                "title": f"{code}: {message[:80]}",
                "message": message,
                "evidence": match.group(0)[:500],
            })

    # Webpack/vite errors: ERROR in src/foo.tsx
    webpack_pattern = re.compile(r"ERROR in ([^\s]+)\s*\n(.*?)(?:\n\n|\Z)", re.DOTALL)
    for match in webpack_pattern.finditer(output):
        file = match.group(1)
        message = match.group(2).strip()
        key = f"webpack:{file}"
        if key not in seen:
            seen.add(key)
            errors.append({
                "file": file,
                "code": "WEBPACK",
                "title": f"Webpack error in {file}",
                "message": message[:500],
                "evidence": match.group(0)[:500],
            })

    return errors


def _agent_analyze_build(
    target: TargetConfig,
    merged: TargetConfig,
    build_result: RunResult,
    metadata: dict[str, Any],
) -> None:
    """Use Claude Agent SDK to analyze build failures. Best-effort."""
    template = load_prompt("build_analyze.md", target.target_dir)
    if template is None:
        return
    assert merged.build is not None

    prompt = render_template(template, {
        "migration_description": target.name,
        "build_cmd": merged.build.build_cmd,
        "exit_code": str(build_result.exit_code),
        "build_output": (build_result.stdout + "\n" + build_result.stderr)[:8000],
    })

    async def _run() -> str:
        return await run_agent_query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=[],
                permission_mode="acceptEdits",
            ),
            prefix="build-llm",
        )

    metadata["llm_build_analysis"] = asyncio.run(_run())
