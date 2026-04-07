"""Bundled prompt templates.

Targets can override any prompt by placing a file with the same name
in their own prompts/ directory.
"""

from __future__ import annotations

from pathlib import Path

BUNDLED_PROMPTS_DIR = Path(__file__).parent


def resolve_prompt(name: str, target_dir: Path) -> Path | None:
    """Resolve a prompt template, checking target override first.

    Returns the path to the prompt file, or None if not found anywhere.
    """
    # Target override
    override = target_dir / "prompts" / name
    if override.exists():
        return override

    # Bundled default
    bundled = BUNDLED_PROMPTS_DIR / name
    if bundled.exists():
        return bundled

    return None


def load_prompt(name: str, target_dir: Path) -> str | None:
    """Load a prompt template by name. Returns None if not found."""
    path = resolve_prompt(name, target_dir)
    if path is None:
        return None
    return path.read_text()
