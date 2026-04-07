"""LLM review evaluation layer using Claude Agent SDK.

Implements the adversarial debate loop:
Critic ↔ Challenger (iterative) → Judge → Consolidator.

Each role is a Claude agent with its own system prompt loaded from
the target's prompts/ directory. The Critic and Challenger have
read-only access to the codebase via Read, Grep, and Glob tools.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
)

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

# Tools that give agents read-only codebase access
_CODE_TOOLS = ["Read", "Grep", "Glob"]


class LlmReviewLayer:
    """Adversarial LLM review of migration evidence using Claude Agent SDK."""

    name: LayerName = "llm"

    def __init__(self, max_rounds: int = 3) -> None:
        self.max_rounds = max_rounds

    def can_run(
        self,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> tuple[bool, str]:
        """Check if required prompt templates are available."""
        required = ["critic.md", "challenger.md", "judge.md", "consolidator.md"]
        for name in required:
            if load_prompt(name, target.target_dir) is None:
                return False, f"Missing prompt template: {name}"
        return True, ""

    def evaluate(
        self,
        path: Path,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> LayerResult:
        """Run the adversarial debate loop via Claude Agent SDK."""
        start = time.monotonic()
        metadata: dict[str, Any] = {}

        # Load agent hints
        hints_path = target.target_dir / "agent_hints.md"
        agent_hints = hints_path.read_text() if hints_path.exists() else ""

        # Build evidence summary from prior layers
        evidence = _build_evidence_summary(context)

        # Template variables shared across roles
        base_vars: dict[str, str] = {
            "migration_description": target.name,
            "codebase_path": str(path.resolve()),
            "issues_summary": evidence["issues_summary"],
            "build_output": evidence["build_output"],
            "runtime_evidence": evidence["runtime_evidence"],
            "delta_summary": evidence.get("delta_summary", ""),
            "agent_hints": agent_hints,
        }

        try:
            result = asyncio.run(
                self._run_debate(
                    path, target.target_dir, base_vars, context, metadata
                )
            )
        except Exception as e:
            metadata["error"] = str(e)
            elapsed = time.monotonic() - start
            return LayerResult(
                layer="llm",
                success=False,
                skip_reason=f"Agent SDK error: {e}",
                duration_seconds=round(elapsed, 2),
                metadata=metadata,
            )

        elapsed = time.monotonic() - start
        return LayerResult(
            layer="llm",
            success=True,
            duration_seconds=round(elapsed, 2),
            issues=result,
            metadata=metadata,
        )

    async def _run_debate(
        self,
        codebase_path: Path,
        target_dir: Path,
        base_vars: dict[str, str],
        context: LayerContext,
        metadata: dict[str, Any],
    ) -> list[Issue]:
        """Run the full adversarial debate using Claude Agent SDK."""

        # Load prompt templates (target override → bundled default)
        critic_tmpl = load_prompt("critic.md", target_dir)
        challenger_tmpl = load_prompt("challenger.md", target_dir)
        judge_tmpl = load_prompt("judge.md", target_dir)
        consolidator_tmpl = load_prompt("consolidator.md", target_dir)

        if not all([critic_tmpl, challenger_tmpl, judge_tmpl, consolidator_tmpl]):
            metadata["error"] = "Missing prompt templates"
            return []

        assert critic_tmpl is not None
        assert challenger_tmpl is not None
        assert judge_tmpl is not None
        assert consolidator_tmpl is not None

        # Build existing issues summary for consolidator
        existing_issues = "\n".join(
            f"- [{i.source}] {i.title} ({i.file})" for i in context.prior_issues
        )

        # Render system prompts for each role
        critic_prompt = render_template(critic_tmpl, base_vars)

        codebase = str(codebase_path.resolve())

        # Build the orchestration prompt
        orchestration_prompt = f"""You are orchestrating an adversarial migration review debate.

The codebase under review is at: {codebase}

Run this loop for up to {self.max_rounds} rounds:
1. Delegate to the "critic" agent — it will explore the codebase and identify potential migration issues
2. Delegate to the "challenger" agent — give it the critic's findings to push back on (the challenger can also read the code to verify claims)
3. If the critic's findings haven't changed much from the previous round, stop the loop

After the loop:
4. Delegate to the "judge" agent with the full debate history
5. Delegate to the "consolidator" agent with the judge's rulings

Return ONLY the consolidator's final JSON output — no additional commentary.

Migration: {base_vars['migration_description']}

Evidence from automated checks:
{base_vars['issues_summary']}

Build output:
{base_vars['build_output']}

Runtime evidence:
{base_vars['runtime_evidence']}"""

        # Define agents for each debate role
        agents = {
            "critic": AgentDefinition(
                description="Migration critic — explores codebase and identifies all potential issues",
                prompt=critic_prompt,
                tools=_CODE_TOOLS,
            ),
            "challenger": AgentDefinition(
                description="Challenger — reads code to verify/refute critic's findings",
                prompt=render_template(challenger_tmpl, base_vars),
                tools=_CODE_TOOLS,
            ),
            "judge": AgentDefinition(
                description="Judge — resolves disputes between critic and challenger",
                prompt=render_template(judge_tmpl, {
                    **base_vars,
                    "critic_issues": "{{critic_issues}}",
                    "challenger_rebuttals": "{{challenger_rebuttals}}",
                }),
                tools=[],
            ),
            "consolidator": AgentDefinition(
                description="Consolidator — deduplicates and produces final structured JSON output",
                prompt=render_template(consolidator_tmpl, {
                    "judge_issues": "{{judge_issues}}",
                    "existing_issues": existing_issues,
                }),
                tools=[],
            ),
        }

        # Run the orchestration
        full_response = await run_agent_query(
            prompt=orchestration_prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Agent"] + _CODE_TOOLS,
                agents=agents,
                permission_mode="acceptEdits",
                cwd=codebase,
            ),
            prefix="llm-review",
        )

        metadata["raw_response"] = full_response[:5000]

        # Parse the response into Issue objects
        return _parse_llm_issues(full_response)


def _build_evidence_summary(context: LayerContext) -> dict[str, str]:
    """Build evidence strings from LayerContext for prompt templates."""
    issues_lines: list[str] = []
    for issue in context.prior_issues:
        loc = f" ({issue.file}:{issue.line})" if issue.file else ""
        issues_lines.append(
            f"- [{issue.severity}] {issue.title}{loc}: {issue.detail[:200]}"
        )

    build_output = str(context.metadata.get("build_stdout", ""))
    build_stderr = str(context.metadata.get("build_stderr", ""))
    build_combined = f"{build_output}\n{build_stderr}".strip()

    runtime_parts: list[str] = []
    screenshots = context.metadata.get("screenshots", {})
    if isinstance(screenshots, dict):
        for name, spath in screenshots.items():
            runtime_parts.append(f"Screenshot: {name} -> {spath}")
    console_errors = context.metadata.get("console_errors", {})
    if isinstance(console_errors, dict):
        for route, errors in console_errors.items():
            if isinstance(errors, list):
                for err in errors:
                    runtime_parts.append(f"Console error on {route}: {err}")

    return {
        "issues_summary": "\n".join(issues_lines) or "No issues found by automated checks.",
        "build_output": build_combined[:8000] or "No build output available.",
        "runtime_evidence": "\n".join(runtime_parts) or "No runtime evidence captured.",
    }


def _parse_llm_issues(response: str) -> list[Issue]:
    """Parse the consolidator's JSON output into Issue objects."""
    issues: list[Issue] = []

    try:
        # Try to extract JSON from response (may have markdown fencing)
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # Strip markdown code fences
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)

        # Try parsing as a JSON object first (may have a "findings" key)
        items: list[dict[str, Any]] = []
        start_obj = cleaned.find("{")
        end_obj = cleaned.rfind("}")
        start_arr = cleaned.find("[")
        end_arr = cleaned.rfind("]")

        if start_obj != -1 and end_obj != -1:
            obj = json.loads(cleaned[start_obj : end_obj + 1])
            if isinstance(obj, dict):
                # Look for findings/issues array inside the object
                items = (
                    obj.get("findings", [])
                    or obj.get("issues", [])
                    or obj.get("results", [])
                )
                if not items and start_arr != -1:
                    # Fall back to extracting bare array
                    items = json.loads(cleaned[start_arr : end_arr + 1])
            elif isinstance(obj, list):
                items = obj
        elif start_arr != -1 and end_arr != -1:
            items = json.loads(cleaned[start_arr : end_arr + 1])

        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "LLM-identified issue"))
            # Handle both "file" (string) and "files" (list) formats
            file_val = item.get("file")
            if file_val is None:
                files = item.get("files", [])
                if isinstance(files, list) and files:
                    file_val = str(files[0])
            issues.append(
                Issue(
                    id=make_issue_id("llm_review", title),
                    source="llm_review",
                    severity=item.get("severity", "medium"),
                    file=file_val,
                    line=item.get("line"),
                    title=title,
                    detail=str(
                        item.get("detail", "")
                        or item.get("description", "")
                    ),
                    evidence=str(item.get("evidence", "")),
                    suggestion=str(
                        item.get("suggestion", "")
                        or item.get("fix", "")
                    ),
                )
            )
    except (json.JSONDecodeError, ValueError, KeyError):
        if response.strip():
            issues.append(
                Issue(
                    id=make_issue_id("llm_review", "unparsed"),
                    source="llm_review",
                    severity="info",
                    title="LLM review (unparsed)",
                    detail=response[:2000],
                )
            )

    return issues
