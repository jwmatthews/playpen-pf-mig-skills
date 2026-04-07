"""Orchestrator: runs layers on before + attempts, compares, reports."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml

from migeval.comparison import compare_attempts
from migeval.config import load_project_config, resolve_target
from migeval.layers.build import BuildLayer
from migeval.layers.llm_review import LlmReviewLayer
from migeval.layers.runtime import RuntimeLayer
from migeval.layers.source import SourceLayer
from migeval.models import (
    AttemptResult,
    EvaluationRun,
    LayerContext,
    LayerName,
    LayerResult,
    ProjectConfig,
    RegressionItem,
    Severity,
    TargetConfig,
)
from migeval.regression import compute_regressions
from migeval.reporting.json_report import write_json_report
from migeval.reporting.markdown_report import generate_markdown_report


def _log(msg: str) -> None:
    """Log a message to stderr."""
    click.echo(msg, err=True)


def _warn_missing_config(
    target: TargetConfig, enabled_layers: Sequence[str]
) -> None:
    """Warn about missing target config that could be bootstrapped."""
    warnings: list[str] = []
    target_name = target.name

    if "source" in enabled_layers:
        if not target.text_patterns:
            warnings.append(
                f"Target '{target_name}' has no text_patterns"
            )
        if not target.dependencies:
            warnings.append(
                f"Target '{target_name}' has no dependencies config"
            )

    if "build" in enabled_layers and target.build is None:
        warnings.append(
            f"Target '{target_name}' has no build config"
        )

    if (
        "runtime" in enabled_layers
        and target.runtime is None
        and not (target.target_dir / "runtime.py").exists()
    ):
        warnings.append(
            f"Target '{target_name}' has no runtime config or runtime.py"
        )

    if "llm" in enabled_layers:
        hints_path = target.target_dir / "agent_hints.md"
        if not hints_path.exists():
            warnings.append(
                f"Target '{target_name}' has no agent_hints.md "
                "(LLM review will use generic prompts only)"
            )

    if not (target.target_dir / "detectors.py").exists():
        warnings.append(
            f"Target '{target_name}' has no detectors.py"
        )

    if warnings:
        _log("⚠ Target config gaps detected:")
        for w in warnings:
            _log(f"  • {w}")
        _log(
            "  Run `migeval bootstrap` to generate missing files"
        )
        _log("")


def run_evaluation(
    before_path: Path,
    attempts: dict[str, Path],
    target_name: str | None = None,
    target_dir: str | None = None,
    config_path: Path | None = None,
    layers: list[LayerName] | None = None,
    violations: dict[str, Path] | None = None,
    previous_run_path: Path | None = None,
    output_dir: Path | None = None,
    llm_max_rounds: int = 3,
) -> EvaluationRun:
    """Run the full evaluation pipeline."""
    target = resolve_target(target_name, target_dir)
    project = load_project_config(config_path) if config_path else None

    enabled_layers = layers or ["source", "build", "runtime", "llm"]

    # Build layer instances
    layer_instances: dict[LayerName, Any] = {}
    if "source" in enabled_layers:
        layer_instances["source"] = SourceLayer()
    if "build" in enabled_layers:
        layer_instances["build"] = BuildLayer()
    if "runtime" in enabled_layers:
        layer_instances["runtime"] = RuntimeLayer()
    if "llm" in enabled_layers:
        layer_instances["llm"] = LlmReviewLayer(max_rounds=llm_max_rounds)

    # Warn about missing target config
    _warn_missing_config(target, enabled_layers)

    _log("migeval v2.0 — Migration Health Evaluation")
    _log("━" * 40)
    _log(f"Before:  {before_path}")
    _log(f"Target:  {target.name}")
    _log(f"Attempts: {', '.join(attempts.keys())}")
    _log("")

    # Evaluate before baseline (all layers except LLM)
    before_result = _evaluate_codebase(
        name="before",
        path=before_path,
        target=target,
        project=project,
        layer_instances={
            k: v for k, v in layer_instances.items() if k != "llm"
        },
        violations_data=None,
        output_dir=output_dir,
    )

    # Evaluate each attempt (all layers including LLM)
    attempt_results: dict[str, AttemptResult] = {}
    for attempt_name, attempt_path in attempts.items():
        violations_data = None
        if violations and attempt_name in violations:
            violations_data = _load_violations(violations[attempt_name])
        elif (attempt_path / "output.yaml").exists():
            violations_data = _load_violations(attempt_path / "output.yaml")

        attempt_results[attempt_name] = _evaluate_codebase(
            name=attempt_name,
            path=attempt_path,
            target=target,
            project=project,
            layer_instances=layer_instances,
            violations_data=violations_data,
            output_dir=output_dir,
        )

    # Comparisons: before vs each attempt
    before_vs: dict[str, Any] = {}
    for name, result in attempt_results.items():
        delta = compare_attempts(before_result, result)
        before_vs[name] = delta
        _log("")
        _log(f"━━━ Comparison: before → {name} ━━━")
        _log(
            f"Resolved: {len(delta.resolved)} issues  |  "
            f"New: {len(delta.new)} issues  |  "
            f"Net: {delta.delta:+d}"
        )

    # Comparisons: attempt vs attempt
    attempt_vs: dict[str, Any] = {}
    attempt_names = list(attempt_results.keys())
    for i in range(len(attempt_names)):
        for j in range(i + 1, len(attempt_names)):
            a_name = attempt_names[i]
            b_name = attempt_names[j]
            delta = compare_attempts(
                attempt_results[a_name], attempt_results[b_name]
            )
            key = f"{a_name}_vs_{b_name}"
            attempt_vs[key] = delta
            _log("")
            _log(f"━━━ Comparison: {a_name} vs {b_name} ━━━")
            if delta.delta < 0:
                _log(f"{b_name} wins by {-delta.delta} fewer issues")
            elif delta.delta > 0:
                _log(f"{a_name} wins by {delta.delta} fewer issues")
            else:
                _log("Tied on issue count")

    # Regression tracking
    regressions: list[RegressionItem] | None = None
    if previous_run_path:
        try:
            with open(previous_run_path) as f:
                prev_data = json.load(f)
            previous_run = EvaluationRun.model_validate(prev_data)
            regressions = compute_regressions(
                EvaluationRun(
                    timestamp=datetime.now(UTC).isoformat(),
                    target=target_name,
                    before=before_result,
                    attempts=attempt_results,
                    before_vs_attempt=before_vs,
                    attempt_vs_attempt=attempt_vs,
                ),
                previous_run,
            )
        except Exception as e:
            _log(f"Warning: Could not load previous run: {e}")

    run = EvaluationRun(
        timestamp=datetime.now(UTC).isoformat(),
        target=target_name,
        before=before_result,
        attempts=attempt_results,
        before_vs_attempt=before_vs,
        attempt_vs_attempt=attempt_vs,
        regressions=regressions,
    )

    # Write output
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_outputs(run, output_dir)

    return run


def _evaluate_codebase(
    name: str,
    path: Path,
    target: TargetConfig,
    project: ProjectConfig | None,
    layer_instances: dict[LayerName, Any],
    violations_data: dict[str, Any] | None,
    output_dir: Path | None = None,
) -> AttemptResult:
    """Run all enabled layers on a single codebase."""
    context = LayerContext(
        violations=violations_data,
        output_dir=output_dir,
        codebase_name=name,
    )
    layer_results: dict[LayerName, LayerResult] = {}

    layer_order: list[LayerName] = ["source", "build", "runtime", "llm"]
    for layer_name in layer_order:
        if layer_name not in layer_instances:
            continue

        layer = layer_instances[layer_name]
        can_run, skip_reason = layer.can_run(target, project, context)

        if not can_run:
            layer_results[layer_name] = LayerResult(
                layer=layer_name,
                success=True,
                skipped=True,
                skip_reason=skip_reason,
                duration_seconds=0.0,
            )
            _log(f"[{layer_name:8s}] ⊘ {name}: skipped ({skip_reason})")
            continue

        result = layer.evaluate(path, target, project, context)
        layer_results[layer_name] = result

        # Update context for subsequent layers
        context.prior_issues.extend(result.issues)
        context.metadata.update(result.metadata)
        if layer_name == "build":
            context.build_passed = result.metadata.get(
                "build_exit_code", -1
            ) == 0

        # Log result
        issue_count = len(result.issues)
        status = "✓" if result.success else "✗"
        extra = ""
        if layer_name == "source":
            matches = result.metadata.get("text_matches", 0)
            deps_ok = result.metadata.get("deps_ok", "?")
            deps_total = result.metadata.get("deps_total", "?")
            extra = f"{deps_ok}/{deps_total} deps, {matches} text matches"
        elif layer_name == "build":
            if context.build_passed:
                extra = f"PASS ({issue_count} errors)"
            else:
                extra = f"FAIL ({issue_count} errors)"
        elif layer_name == "runtime":
            extra = f"{issue_count} issues captured"
        elif layer_name == "llm":
            extra = f"{issue_count} issues found"

        dur = f"({result.duration_seconds}s)"
        _log(f"[{layer_name:8s}] {status} {name}: {extra} {dur}")

    # Compute summary
    total_issues = sum(
        len(lr.issues) for lr in layer_results.values()
    )
    severity_counts: dict[Severity, int] = {}
    for lr in layer_results.values():
        for issue in lr.issues:
            severity_counts[issue.severity] = (
                severity_counts.get(issue.severity, 0) + 1
            )

    return AttemptResult(
        name=name,
        path=str(path),
        layer_results=layer_results,
        total_issues=total_issues,
        issues_by_severity=severity_counts,
        build_passes=context.build_passed,
    )


def _load_violations(path: Path) -> dict[str, Any] | None:
    """Load violations from a YAML or JSON file."""
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            data: Any = yaml.safe_load(f)
        else:
            data = json.load(f)
    if isinstance(data, dict):
        return data
    return None


def _write_outputs(run: EvaluationRun, output_dir: Path) -> None:
    """Write evaluation.json and report.md to output_dir."""
    write_json_report(run, output_dir / "evaluation.json")
    md = generate_markdown_report(run)
    (output_dir / "report.md").write_text(md)
    _log(f"\nOutput written to {output_dir}/")
