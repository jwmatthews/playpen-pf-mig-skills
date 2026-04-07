"""Runtime evaluation layer.

Captures runtime evidence: screenshots, console errors.
Uses target's runtime.py if available, otherwise uses Claude Agent SDK
with the Playwright MCP server for browser-based evidence capture.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from migeval.config import load_target_module, merge_configs
from migeval.models import (
    Issue,
    LayerContext,
    LayerName,
    LayerResult,
    ProjectConfig,
    TargetConfig,
    make_issue_id,
)
from migeval.util.agent import run_agent_query


class RuntimeLayer:
    """Captures runtime evidence via target's runtime.py or Playwright MCP."""

    name: LayerName = "runtime"

    def can_run(
        self,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> tuple[bool, str]:
        """Check if runtime evaluation is possible."""
        if context.build_passed is False:
            return False, "Build failed"

        merged = merge_configs(target, project)

        has_runtime_py = (target.target_dir / "runtime.py").exists()
        has_runtime_config = merged.runtime is not None

        if not has_runtime_py and not has_runtime_config:
            return False, "No runtime config or runtime.py"

        return True, ""

    def evaluate(
        self,
        path: Path,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> LayerResult:
        """Run runtime evaluation."""
        start = time.monotonic()
        merged = merge_configs(target, project)
        issues: list[Issue] = []
        metadata: dict[str, Any] = {}

        # Try target's runtime.py first
        runtime_module = load_target_module(target.target_dir, "runtime")
        if runtime_module is not None:
            check_fn = getattr(runtime_module, "check", None)
            if check_fn is not None:
                result = check_fn(path, merged, context)
                if isinstance(result, dict):
                    issues.extend(
                        Issue(**i) for i in result.get("issues", [])
                    )
                    metadata.update(result.get("metadata", {}))

        # Fall back to Playwright MCP agent
        elif merged.runtime is not None:
            pw_issues, pw_meta = _playwright_mcp_capture(
                path, merged, context.output_dir, context.codebase_name
            )
            issues.extend(pw_issues)
            metadata.update(pw_meta)

        elapsed = time.monotonic() - start
        metadata["routes_checked"] = len(merged.routes)

        return LayerResult(
            layer="runtime",
            success=True,
            duration_seconds=round(elapsed, 2),
            issues=issues,
            metadata=metadata,
        )


def _playwright_mcp_capture(
    path: Path,
    config: TargetConfig,
    output_dir: Path | None,
    codebase_name: str,
) -> tuple[list[Issue], dict[str, Any]]:
    """Use Claude Agent SDK + Playwright MCP server to capture runtime evidence.

    Starts the dev server, then launches an agent with the Playwright MCP server
    to navigate routes, take screenshots, and capture console errors.
    """
    issues: list[Issue] = []
    metadata: dict[str, Any] = {}
    assert config.runtime is not None

    if output_dir is not None:
        screenshot_dir = output_dir / "screenshots" / codebase_name
    else:
        screenshot_dir = path / ".migeval-screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    # Build route descriptions for the agent
    routes_desc = "\n".join(
        f"- {r.name}: http://localhost:{config.runtime.port}{r.path}"
        + (f" (wait for CSS selector: {r.wait_for})" if r.wait_for else "")
        for r in config.routes
    ) or f"- home: http://localhost:{config.runtime.port}/"

    prompt = f"""You are capturing runtime evidence for a migration evaluation.

A dev server is already running at http://localhost:{config.runtime.port}.

## Routes to check:
{routes_desc}

## Tasks:
For each route:
1. Navigate to the URL using the Playwright MCP browser
2. Wait for the page to fully load
3. Take a screenshot and save it to: {screenshot_dir}/<route_name>.png
4. Check for any JavaScript console errors
5. Note any visual issues (blank pages, broken layouts, missing content)

## Output format:
After checking all routes, output ONLY a JSON object (no markdown fencing) with this structure:
{{
  "routes": [
    {{
      "name": "route_name",
      "url": "http://...",
      "status": "ok" | "error" | "blank",
      "screenshot_path": "/path/to/screenshot.png",
      "console_errors": ["error text", ...],
      "visual_notes": "any observations about the page"
    }}
  ]
}}
"""

    # Start the dev server as a background process
    server_proc: subprocess.Popen[bytes] | None = None
    try:
        server_proc = subprocess.Popen(
            config.runtime.dev_server_cmd,
            shell=True,
            cwd=str(path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        # Wait for server to be ready
        _wait_for_server(
            config.runtime.port,
            timeout=config.runtime.startup_timeout,
        )
        metadata["dev_server_started"] = True

        # Run the agent with Playwright MCP
        result_text = asyncio.run(_run_playwright_agent(prompt, screenshot_dir))
        metadata["agent_raw_response"] = result_text[:5000]

        # Parse agent response
        parsed_issues, parsed_meta = _parse_playwright_result(result_text)
        issues.extend(parsed_issues)
        metadata.update(parsed_meta)

    except Exception as e:
        metadata["playwright_mcp_error"] = str(e)
        metadata["dev_server_started"] = metadata.get("dev_server_started", False)
        raise RuntimeError(f"Playwright MCP runtime capture failed: {e}") from e

    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)

    return issues, metadata


async def _run_playwright_agent(prompt: str, screenshot_dir: Path) -> str:
    """Run the Agent SDK with Playwright MCP server attached."""
    return await run_agent_query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            allowed_tools=["mcp__playwright__*", "Bash"],
            mcp_servers={
                "playwright": {
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp@latest"],
                },
            },
            permission_mode="bypassPermissions",
            cwd=str(screenshot_dir),
            max_turns=30,
        ),
        prefix="runtime-pw",
    )


def _wait_for_server(port: int, timeout: int = 120) -> None:
    """Wait for a server to respond on the given port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{port}/", timeout=5
            )
            if resp.status == 200:
                return
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(2)
    raise TimeoutError(
        f"Dev server did not respond on port {port} within {timeout}s"
    )


def _parse_playwright_result(
    response: str,
) -> tuple[list[Issue], dict[str, Any]]:
    """Parse the Playwright agent's JSON response into issues + metadata."""
    issues: list[Issue] = []
    metadata: dict[str, Any] = {
        "screenshots": {},
        "console_errors": {},
    }

    try:
        start = response.find("{")
        end = response.rfind("}")
        if start == -1 or end == -1:
            return issues, metadata

        data = json.loads(response[start : end + 1])
        routes = data.get("routes", [])

        for route in routes:
            name = route.get("name", "unknown")
            screenshot = route.get("screenshot_path", "")
            console_errors = route.get("console_errors", [])
            status = route.get("status", "ok")
            visual_notes = route.get("visual_notes", "")

            if screenshot:
                metadata["screenshots"][name] = screenshot

            if console_errors:
                metadata["console_errors"][name] = console_errors
                for err_text in console_errors:
                    issues.append(
                        Issue(
                            id=make_issue_id(
                                "runtime_error", name, err_text[:50]
                            ),
                            source="runtime_error",
                            severity="medium",
                            title=f"Console error on /{name}",
                            detail=err_text[:500],
                            evidence=err_text,
                        )
                    )

            if status == "error":
                issues.append(
                    Issue(
                        id=make_issue_id("runtime_error", name, "page_error"),
                        source="runtime_error",
                        severity="high",
                        title=f"Route /{name} failed to load",
                        detail=visual_notes or "Page returned an error",
                        evidence=visual_notes,
                    )
                )
            elif status == "blank":
                issues.append(
                    Issue(
                        id=make_issue_id("runtime_visual", name, "blank"),
                        source="runtime_visual",
                        severity="warning",
                        title=f"Route /{name} appears blank",
                        detail=visual_notes or "Page rendered with no visible content",
                        evidence=visual_notes,
                    )
                )

            if screenshot:
                issues.append(
                    Issue(
                        id=make_issue_id("runtime_visual", name),
                        source="runtime_visual",
                        severity="info",
                        title=f"Visual capture: /{name}",
                        detail=f"Screenshot saved to {screenshot}",
                        evidence=screenshot,
                    )
                )

    except (json.JSONDecodeError, ValueError, KeyError):
        if response.strip():
            metadata["parse_error"] = "Failed to parse agent response as JSON"

    return issues, metadata
