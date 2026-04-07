"""Layer protocol and shared types."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from migeval.models import (
    LayerContext,
    LayerName,
    LayerResult,
    ProjectConfig,
    TargetConfig,
)


class EvaluationLayer(Protocol):
    """Protocol that all evaluation layers implement.

    Layers that need LLM access use the Claude Agent SDK directly.
    """

    name: LayerName

    def can_run(
        self,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> tuple[bool, str]:
        """Check if this layer can run. Returns (can_run, skip_reason)."""
        ...

    def evaluate(
        self,
        path: Path,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> LayerResult:
        """Run evaluation on the given path. Returns results."""
        ...
