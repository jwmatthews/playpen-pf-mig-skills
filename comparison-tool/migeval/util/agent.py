"""Shared Agent SDK runner with progress logging."""

from __future__ import annotations

from typing import Any

import click
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)


def log_agent(prefix: str, msg: str) -> None:
    """Log an agent progress message to stderr."""
    click.echo(f"[{prefix:12s}] {msg}", err=True)


async def run_agent_query(
    prompt: str,
    options: ClaudeAgentOptions,
    prefix: str = "agent",
) -> str:
    """Run an Agent SDK query with progress logging.

    Logs tool calls, text output, and usage info to stderr.
    Returns the final result text.
    """
    result_text = ""
    turn = 0

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, SystemMessage):
            subtype = getattr(message, "subtype", "")
            if subtype == "init":
                data = getattr(message, "data", {}) or {}
                session_id = (
                    data.get("session_id", "") if isinstance(data, dict) else ""
                )
                log_agent(prefix, f"Session started: {str(session_id)[:12]}...")

        elif isinstance(message, AssistantMessage):
            turn += 1
            content = getattr(message, "content", [])
            if not isinstance(content, list):
                content = []

            for block in content:
                if isinstance(block, TextBlock):
                    text = block.text.strip()
                    if text:
                        for line in text.split("\n"):
                            log_agent(prefix, line)

                elif isinstance(block, ToolUseBlock):
                    summary = _summarize_tool_call(block.name, block.input)
                    log_agent(prefix, f"→ {block.name}: {summary}")

                elif isinstance(block, ToolResultBlock):
                    pass  # tool results are verbose, skip

                elif isinstance(block, ThinkingBlock):
                    log_agent(prefix, "(thinking...)")

            # Log usage (usage is dict[str, Any] | None)
            usage = message.usage
            if usage and isinstance(usage, dict):
                input_t = usage.get("input_tokens", 0)
                output_t = usage.get("output_tokens", 0)
                log_agent(
                    prefix,
                    f"turn {turn} | "
                    f"{input_t:,} in / {output_t:,} out",
                )

        elif isinstance(message, ResultMessage):
            result_text = str(message.result or "")
            cost = message.total_cost_usd
            if cost:
                log_agent(
                    prefix,
                    f"Done (cost: ${cost:.4f}, {message.num_turns} turns)",
                )
            else:
                log_agent(prefix, f"Done ({message.num_turns} turns)")

        else:
            # Log other message types for visibility
            msg_type = type(message).__name__
            # TaskProgress, RateLimitEvent, etc.
            if hasattr(message, "subtype"):
                log_agent(prefix, f"{msg_type}: {message.subtype}")

    return result_text


def _summarize_tool_call(
    tool_name: str, tool_input: Any
) -> str:
    """Create a short summary of a tool call for logging."""
    if not isinstance(tool_input, dict):
        return str(tool_input)

    if tool_name in ("Read", "Write", "Edit"):
        return str(tool_input.get("file_path", ""))

    if tool_name in ("Glob", "Grep"):
        return str(tool_input.get("pattern", ""))

    if tool_name == "Bash":
        return str(tool_input.get("command", ""))

    if tool_name == "WebSearch":
        return f'"{tool_input.get("query", "")}"'

    if tool_name == "WebFetch":
        return str(tool_input.get("url", ""))

    if tool_name == "Agent":
        return str(tool_input.get("description", ""))

    # Fallback
    return str(tool_input)
