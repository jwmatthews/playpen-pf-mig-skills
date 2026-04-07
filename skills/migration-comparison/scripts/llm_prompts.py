#!/usr/bin/env python3
"""
Prompt templates and JSON schemas for the LLM adversarial review loop.

Each role (Critic, Challenger, Judge, Consolidator) has:
- A prompt template function that takes context and returns the full prompt
- A JSON schema for structured output
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# JSON Schemas for structured output
# ---------------------------------------------------------------------------

CRITIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "file": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["id", "file", "severity", "title", "description", "evidence", "confidence"],
            },
        },
    },
    "required": ["issues"],
}

CHALLENGER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "challenges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["upheld", "dismissed", "severity_reduced"]},
                    "reasoning": {"type": "string"},
                    "suggested_severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                },
                "required": ["issue_id", "verdict", "reasoning"],
            },
        },
    },
    "required": ["challenges"],
}

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["real", "not_real"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "final_severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["issue_id", "verdict", "confidence", "final_severity", "reasoning"],
            },
        },
    },
    "required": ["verdicts"],
}

CONSOLIDATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "theme": {"type": "string"},
                    "description": {"type": "string"},
                    "affected_files": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["severity", "theme", "description", "affected_files", "confidence"],
            },
        },
    },
    "required": ["themes"],
}


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_critic_prompt(
    review_input: dict[str, Any],
    previous_judge: dict[str, Any] | None = None,
    round_num: int = 1,
) -> str:
    """Build the Critic prompt for a given round."""
    files_section = _format_review_files(review_input)

    base = f"""You are a migration quality critic. You are evaluating an AI agent's migration of a codebase from PatternFly 5 to PatternFly 6.

You have access to the golden truth (expert human migration) and the AI agent's attempt. Your job is to identify HIGH-LEVEL migration issues — things that are conceptually wrong, architecturally broken, or functionally incorrect.

**DO NOT** flag line-level differences like "prop X differs" or "import path Y is different." The deterministic layer handles those. Instead focus on:
- Did the migration adopt the new component architecture correctly?
- Does the approach actually work, or does it just look right?
- Are there non-obvious migration requirements that were missed?
- Is the AI's approach a fundamentally different (and broken) pattern?

Remember: 10 engineers would produce 10 different valid migrations. Only flag issues where the AI's approach is actually WRONG or BROKEN, not just different.

## Files to Review

{files_section}
"""

    if previous_judge and round_num > 1:
        judge_summary = _format_judge_summary(previous_judge)
        base += f"""
## Previous Round Judge Verdicts

The judge reviewed your previous findings. Refine your analysis based on their feedback. Drop dismissed issues, strengthen issues marked as needing more evidence, and add any new issues you discover.

{judge_summary}
"""

    base += """
## Output

Identify issues. For each issue provide:
- A unique ID (e.g., "issue-1")
- The file path
- Severity: critical (app broken), high (significant functionality affected), medium (degraded but functional), low (cosmetic/minor)
- A clear title
- A description explaining WHAT is wrong and WHY it matters (assume the reader doesn't know PatternFly)
- Evidence: specific code or patterns that demonstrate the issue
- Confidence (0.0 to 1.0)

Return your findings as structured JSON."""

    return base


def build_challenger_prompt(
    review_input: dict[str, Any],
    critic_output: dict[str, Any],
) -> str:
    """Build the Challenger prompt."""
    files_section = _format_review_files(review_input)
    critic_issues = _format_critic_issues(critic_output)

    return f"""You are a migration quality challenger. You DEFEND the AI agent's migration attempt.

The critic has identified issues with the AI's PatternFly 5 to 6 migration. Your job is to challenge each finding:
- Is the AI's approach a valid alternative? 10 engineers could write this 10 ways.
- Is the critic being too literal (expecting exact golden truth match)?
- Does the issue actually affect functionality, or is it a style difference?
- Is the evidence actually conclusive?

Be rigorous but fair. If an issue is genuinely real, say so (verdict: "upheld"). Only dismiss issues that are genuinely not problems.

## Files Under Review

{files_section}

## Critic's Issues

{critic_issues}

## Output

For each issue, provide:
- The issue_id
- Your verdict: "upheld" (real issue), "dismissed" (not a real issue), or "severity_reduced" (real but less severe)
- Your reasoning
- If severity_reduced, your suggested_severity

Return your challenges as structured JSON."""


def build_judge_prompt(
    review_input: dict[str, Any],
    critic_output: dict[str, Any],
    challenger_output: dict[str, Any],
) -> str:
    """Build the Judge prompt."""
    files_section = _format_review_files(review_input)
    debate = _format_debate(critic_output, challenger_output)

    return f"""You are a migration quality judge. You render final verdicts on disputed migration issues.

The critic identified issues with an AI agent's PatternFly 5 to 6 migration. The challenger defended the AI's approach. You must weigh both arguments and render a verdict.

Your standard: Does the AI's migration WORK CORRECTLY? Not "does it match the golden truth exactly" but "is this a valid, functional migration?"

## Files Under Review

{files_section}

## Debate

{debate}

## Output

For each issue, provide:
- The issue_id
- Your verdict: "real" (genuine issue) or "not_real" (valid alternative or false positive)
- Your confidence (0.0 to 1.0) — how certain you are of this verdict
- The final severity if real (critical/high/medium/low)
- Your reasoning — explain why you sided with critic or challenger

Return your verdicts as structured JSON."""


def build_consolidator_prompt(
    judge_output: dict[str, Any],
    attempt_name: str,
) -> str:
    """Build the Consolidator prompt."""
    verdicts = _format_final_verdicts(judge_output)

    return f"""You are a migration quality consolidator. You distill per-file issue verdicts into high-level themes.

The judge has rendered final verdicts on issues found in the "{attempt_name}" AI migration attempt (PatternFly 5 to PatternFly 6). Your job is to identify 3-7 cross-cutting themes that explain WHERE and WHY the AI agent struggles.

**DO NOT** produce a flat list of per-file issues. Instead, find PATTERNS across files:
- "The AI consistently fails to handle X pattern"
- "Component Y migrations are architecturally wrong because..."
- "The AI applies standard patterns to non-standard code (vendor libraries, custom integrations)"

Each theme must be understandable without PatternFly domain expertise. Explain WHAT the migration issue is and WHY it matters in plain language.

## Final Verdicts (real issues only)

{verdicts}

## Output

Produce 3-7 themes. For each:
- severity: critical/high/medium/low
- theme: short title (e.g., "Incomplete theming/dark mode support")
- description: 2-3 sentences explaining what went wrong and why it matters. Assume the reader doesn't know PatternFly.
- affected_files: list of file paths affected by this theme
- confidence: 0.0 to 1.0

Return your themes as structured JSON."""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_review_files(review_input: dict[str, Any]) -> str:
    """Format file review data into a readable section."""
    parts: list[str] = []
    for file_data in review_input.get("files", []):
        path = file_data.get("path", "unknown")
        parts.append(f"### {path}")

        if file_data.get("before_content"):
            content = file_data["before_content"]
            if len(content) > 3000:
                content = content[:3000] + "\n... (truncated)"
            parts.append(f"**Before migration (original source):**\n```\n{content}\n```")

        if file_data.get("golden_content"):
            content = file_data["golden_content"]
            if len(content) > 5000:
                content = content[:5000] + "\n... (truncated)"
            parts.append(f"**Golden truth (expert migration):**\n```\n{content}\n```")

        if file_data.get("attempt_content"):
            content = file_data["attempt_content"]
            if len(content) > 5000:
                content = content[:5000] + "\n... (truncated)"
            parts.append(f"**AI attempt:**\n```\n{content}\n```")

        if file_data.get("diff"):
            diff = file_data["diff"]
            if len(diff) > 3000:
                diff = diff[:3000] + "\n... (truncated)"
            parts.append(f"**Diff (golden vs attempt):**\n```diff\n{diff}\n```")

        if file_data.get("pattern_results"):
            pr_lines = []
            for pr in file_data["pattern_results"]:
                pr_lines.append(f"  - {pr.get('name', pr.get('pattern_id', '?'))}: {pr.get('status', '?')} — {pr.get('message', '')}")
            parts.append("**Deterministic pattern results:**\n" + "\n".join(pr_lines))

        parts.append("")

    return "\n".join(parts)


def _format_critic_issues(critic_output: dict[str, Any]) -> str:
    """Format critic issues for the challenger."""
    parts: list[str] = []
    for issue in critic_output.get("issues", []):
        parts.append(f"""**{issue['id']}** [{issue.get('severity', '?')}] — {issue.get('title', '')}
File: {issue.get('file', '?')}
Description: {issue.get('description', '')}
Evidence: {issue.get('evidence', '')}
Confidence: {issue.get('confidence', '?')}
""")
    return "\n".join(parts) if parts else "No issues found."


def _format_debate(
    critic_output: dict[str, Any],
    challenger_output: dict[str, Any],
) -> str:
    """Format the critic/challenger debate for the judge."""
    challenges_by_id = {
        c["issue_id"]: c for c in challenger_output.get("challenges", [])
    }

    parts: list[str] = []
    for issue in critic_output.get("issues", []):
        issue_id = issue["id"]
        challenge = challenges_by_id.get(issue_id, {})

        parts.append(f"""### {issue_id}: {issue.get('title', '')}

**Critic** [{issue.get('severity', '?')}] (confidence: {issue.get('confidence', '?')}):
{issue.get('description', '')}
Evidence: {issue.get('evidence', '')}

**Challenger** verdict: {challenge.get('verdict', 'no response')}
{challenge.get('reasoning', 'No challenge provided.')}
""")

    return "\n".join(parts) if parts else "No issues to judge."


def _format_judge_summary(judge_output: dict[str, Any]) -> str:
    """Format judge verdicts for the next critic round."""
    parts: list[str] = []
    for v in judge_output.get("verdicts", []):
        parts.append(
            f"- **{v['issue_id']}**: {v['verdict']} (confidence: {v.get('confidence', '?')}, "
            f"severity: {v.get('final_severity', '?')}) — {v.get('reasoning', '')}"
        )
    return "\n".join(parts) if parts else "No previous verdicts."


def _format_final_verdicts(judge_output: dict[str, Any]) -> str:
    """Format only real verdicts for the consolidator."""
    parts: list[str] = []
    for v in judge_output.get("verdicts", []):
        if v.get("verdict") == "real":
            parts.append(
                f"- **{v['issue_id']}** [{v.get('final_severity', '?')}] "
                f"(confidence: {v.get('confidence', '?')}): {v.get('reasoning', '')}"
            )
    return "\n".join(parts) if parts else "No real issues confirmed."
