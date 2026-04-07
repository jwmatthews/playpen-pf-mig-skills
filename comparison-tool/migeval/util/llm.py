"""Shared LLM client for migeval."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from openai import OpenAI


@dataclass
class TokenUsage:
    """Track token usage across prompts."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_calls: int = 0


@dataclass
class SimpleLlmClient:
    """Simple LLM client using OpenAI-compatible API.

    Implements the LlmClient protocol.
    """

    model: str = "gpt-4o"
    base_url: str | None = None
    api_key: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)

    def prompt(self, template: str, variables: dict[str, str]) -> str:
        """Render template and send to LLM."""
        rendered = render_template(template, variables)

        client = OpenAI(
            api_key=self.api_key or None,
            base_url=self.base_url or None,
        )

        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": rendered}],
            temperature=0.2,
        )

        self.usage.total_calls += 1
        if response.usage:
            self.usage.prompt_tokens += response.usage.prompt_tokens
            self.usage.completion_tokens += response.usage.completion_tokens

        return response.choices[0].message.content or ""


def render_template(template: str, variables: dict[str, str]) -> str:
    """Render a markdown template with {{variable}} placeholders."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    # Remove any remaining unresolved placeholders
    result = re.sub(r"\{\{[^}]+\}\}", "", result)
    return result
