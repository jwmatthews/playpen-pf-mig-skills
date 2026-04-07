"""Data models for migeval.

All types are Pydantic v2 models with strict typing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Literal types ---

LayerName = Literal["source", "build", "runtime", "llm"]
IssueSource = Literal[
    "source_match",
    "source_detector",
    "source_dependency",
    "source_violation",
    "build_error",
    "runtime_error",
    "runtime_visual",
    "llm_review",
]
Severity = Literal["critical", "high", "medium", "low", "warning", "info"]


# --- Config sub-models ---


class TextPattern(BaseModel):
    """A regex pattern to scan source files for."""

    id: str
    pattern: str
    severity: Severity
    title: str
    suggestion: str = ""
    extensions: list[str] = Field(default_factory=list)
    exclude_on_line: str = ""


class DependencyExpectation(BaseModel):
    """An expected dependency name and version."""

    name: str
    version: str


class DependencyConfig(BaseModel):
    """Expected dependencies for the target framework."""

    expected: list[DependencyExpectation] = Field(default_factory=list)


class BuildConfig(BaseModel):
    """Build commands."""

    install_cmd: str
    build_cmd: str


class RuntimeConfig(BaseModel):
    """Runtime / dev server configuration."""

    dev_server_cmd: str
    port: int
    ready_pattern: str = ""
    startup_timeout: int = 120


class RouteConfig(BaseModel):
    """A route to screenshot during runtime evaluation."""

    path: str
    name: str
    wait_for: str = ""


class DocRef(BaseModel):
    """Reference to external documentation."""

    url: str
    description: str = ""


class TargetConfig(BaseModel):
    """Loaded from target.yaml. Carries resolved target dir path for dynamic loading."""

    target_dir: Path
    name: str
    framework: str
    dependencies: DependencyConfig | None = None
    text_patterns: list[TextPattern] = Field(default_factory=list)
    build: BuildConfig | None = None
    runtime: RuntimeConfig | None = None
    routes: list[RouteConfig] = Field(default_factory=list)
    docs: list[DocRef] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    """Loaded from --config YAML. Overrides TargetConfig values per-project."""

    project: dict[str, str] | None = None
    build: BuildConfig | None = None
    runtime: RuntimeConfig | None = None
    routes: list[RouteConfig] = Field(default_factory=list)
    hints: str = ""


# --- Layer context ---


class LayerContext(BaseModel):
    """Evidence accumulated from prior layers, passed to each subsequent layer."""

    prior_issues: list[Issue] = Field(default_factory=list)
    build_passed: bool | None = None
    violations: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_dir: Path | None = None
    codebase_name: str = ""


# --- Core models ---


class Issue(BaseModel):
    """A single issue found during evaluation."""

    id: str
    source: IssueSource
    severity: Severity
    file: str | None = None
    line: int | None = None
    title: str
    detail: str
    evidence: str = ""
    suggestion: str = ""
    pattern_id: str | None = None


class LayerResult(BaseModel):
    """Result from a single evaluation layer."""

    layer: LayerName
    success: bool
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float
    issues: list[Issue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttemptResult(BaseModel):
    """Evaluation results for a single attempt (or the before baseline)."""

    name: str
    path: str
    git_ref: str | None = None
    layer_results: dict[LayerName, LayerResult] = Field(default_factory=dict)
    total_issues: int = 0
    issues_by_severity: dict[Severity, int] = Field(default_factory=dict)
    build_passes: bool | None = None


class AttemptDelta(BaseModel):
    """Comparison between two attempts (or before vs attempt)."""

    attempt_a: str
    attempt_b: str
    resolved: list[str] = Field(default_factory=list)
    new: list[str] = Field(default_factory=list)
    shared: list[str] = Field(default_factory=list)
    delta: int = 0


class RegressionItem(BaseModel):
    """A change detected between two evaluation runs."""

    issue_id: str
    status: Literal["new", "resolved", "changed"]
    current: Issue | None = None
    previous: Issue | None = None
    detail: str = ""


class EvaluationRun(BaseModel):
    """Top-level output of a migeval evaluate run."""

    version: str = "2.0"
    timestamp: str
    target: str | None = None
    before: AttemptResult
    attempts: dict[str, AttemptResult] = Field(default_factory=dict)
    before_vs_attempt: dict[str, AttemptDelta] = Field(default_factory=dict)
    attempt_vs_attempt: dict[str, AttemptDelta] = Field(default_factory=dict)
    regressions: list[RegressionItem] | None = None


# --- Issue ID helpers ---


def make_issue_id(*parts: str) -> str:
    """Create a deterministic issue ID from component parts."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
