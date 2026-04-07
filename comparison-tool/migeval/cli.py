"""CLI for migeval."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from migeval.bootstrap import run_bootstrap
from migeval.models import EvaluationRun, LayerName
from migeval.orchestrator import run_evaluation
from migeval.regression import compute_regressions
from migeval.reporting.markdown_report import generate_markdown_report


def _parse_name_path(value: str) -> tuple[str, Path]:
    """Parse 'name=path' or just 'path' (name defaults to directory name)."""
    if "=" in value:
        name, path_str = value.split("=", 1)
        return name, Path(path_str)
    p = Path(value)
    return p.name, p


@click.group()
def main() -> None:
    """migeval — Migration Health Evaluation Tool."""
    pass


@main.command()
@click.option(
    "--before", required=True, type=str, help="Path to before-migration code"
)
@click.option(
    "--attempt",
    multiple=True,
    type=str,
    help="name=path to a migration attempt (repeatable)",
)
@click.option("--target", "target_name", type=str, help="Bundled target name")
@click.option("--target-dir", type=str, help="External target directory")
@click.option(
    "--config", "config_path",
    type=click.Path(exists=True),
    help="Project config YAML",
)
@click.option(
    "--layers",
    type=str,
    default=None,
    help="Comma-separated layers to run (default: all)",
)
@click.option(
    "--violations",
    multiple=True,
    type=str,
    help="name=path to violations file (repeatable)",
)
@click.option(
    "--previous-run",
    type=click.Path(exists=True),
    help="Previous evaluation.json for regression tracking",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    default="./eval-output",
    help="Output directory (default: ./eval-output)",
)
@click.option(
    "--llm-max-rounds",
    type=int,
    default=3,
    help="Max adversarial debate rounds (default: 3)",
)
@click.option(
    "--fail-on",
    type=str,
    default=None,
    help="Exit code 2 condition (e.g., 'build-fail')",
)
def evaluate(
    before: str,
    attempt: tuple[str, ...],
    target_name: str | None,
    target_dir: str | None,
    config_path: str | None,
    layers: str | None,
    violations: tuple[str, ...],
    previous_run: str | None,
    output_dir: str,
    llm_max_rounds: int,
    fail_on: str | None,
) -> None:
    """Evaluate migration attempts against a before-migration baseline."""

    # Input validation

    if not attempt:
        click.echo("Error: at least one --attempt is required", err=True)
        sys.exit(1)

    before_path = Path(before)
    if not before_path.is_dir():
        click.echo(f"Error: before path not found: {before}", err=True)
        sys.exit(1)

    # Parse attempts
    attempts: dict[str, Path] = {}
    for a in attempt:
        name, path = _parse_name_path(a)
        if not path.is_dir():
            click.echo(f"Error: attempt path not found: {path}", err=True)
            sys.exit(1)
        attempts[name] = path

    # Parse violations
    violations_map: dict[str, Path] | None = None
    if violations:
        violations_map = {}
        for v in violations:
            name, path = _parse_name_path(v)
            violations_map[name] = path

    # Parse layers
    layer_list: list[LayerName] | None = None
    if layers:
        layer_list = []
        for layer_str in layers.split(","):
            layer_str = layer_str.strip()
            if layer_str in ("source", "build", "runtime", "llm"):
                layer_list.append(layer_str)  # type: ignore[arg-type]
            else:
                click.echo(f"Warning: unknown layer '{layer_str}'", err=True)

    run = run_evaluation(
        before_path=before_path,
        attempts=attempts,
        target_name=target_name,
        target_dir=target_dir,
        config_path=Path(config_path) if config_path else None,
        layers=layer_list,
        violations=violations_map,
        previous_run_path=Path(previous_run) if previous_run else None,
        output_dir=Path(output_dir),
        llm_max_rounds=llm_max_rounds,
    )

    # Print markdown report to stdout
    md = generate_markdown_report(run)
    click.echo(md)

    # Check fail-on conditions
    if fail_on == "build-fail":
        for name, attempt_result in run.attempts.items():
            if attempt_result.build_passes is False:
                click.echo(
                    f"\nFail condition met: {name} build failed",
                    err=True,
                )
                sys.exit(2)


@main.command()
@click.option(
    "--before", type=str, default=None,
    help="Path to before-migration code (optional, improves quality)",
)
@click.option(
    "--description", required=True, type=str,
    help="Migration description (e.g. 'PatternFly 5 to PatternFly 6')",
)
@click.option(
    "--output-dir", required=True, type=click.Path(),
    help="Directory to write the generated target to",
)
@click.option(
    "--max-turns", type=int, default=200,
    help="Max agent turns (default: 200)",
)
@click.option(
    "--max-budget", type=float, default=50.0,
    help="Max budget in USD (default: 50.0)",
)
def bootstrap(
    before: str | None,
    description: str,
    output_dir: str,
    max_turns: int,
    max_budget: float,
) -> None:
    """Bootstrap a complete migration evaluation target using LLM + web research."""

    before_path: Path | None = None
    if before:
        before_path = Path(before)
        if not before_path.is_dir():
            click.echo(f"Error: before path not found: {before}", err=True)
            sys.exit(1)

    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    click.echo(f"Bootstrapping target for: {description}", err=True)
    if before_path:
        click.echo(f"Before codebase: {before_path}", err=True)
    else:
        click.echo("No before codebase — using web research only", err=True)
    click.echo(f"Output: {out}", err=True)
    click.echo(f"Budget: ${max_budget:.2f}, max turns: {max_turns}", err=True)
    click.echo("", err=True)

    run_bootstrap(
        before_path=before_path,
        description=description,
        output_dir=out,
        max_turns=max_turns,
        max_budget_usd=max_budget,
    )


@main.command()
def check() -> None:
    """Check that the Claude Agent SDK can connect to an LLM backend."""

    click.echo("Checking Claude Agent SDK connectivity...", err=True)

    async def _check() -> None:

        got_response = False
        async for message in query(
            prompt="Respond with exactly: MIGEVAL_OK",
            options=ClaudeAgentOptions(
                allowed_tools=[],
                max_turns=1,
            ),
        ):
            if isinstance(message, ResultMessage):
                click.echo(f"Result: {message.result}", err=True)
                got_response = True
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        click.echo(f"Response: {block.text}", err=True)
                        got_response = True

        if not got_response:
            click.echo("Warning: no response received", err=True)

    try:
        asyncio.run(_check())
        click.echo("LLM connectivity: OK", err=True)
    except Exception as e:
        click.echo("LLM connectivity: FAILED", err=True)
        click.echo(f"  Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("run_a", type=click.Path(exists=True))
@click.argument("run_b", type=click.Path(exists=True))
def compare(run_a: str, run_b: str) -> None:
    """Compare two evaluation runs for regression tracking."""
    with open(run_a) as f:
        data_a = json.load(f)
    with open(run_b) as f:
        data_b = json.load(f)

    prev = EvaluationRun.model_validate(data_a)
    curr = EvaluationRun.model_validate(data_b)

    regressions = compute_regressions(curr, prev)

    if not regressions:
        click.echo("No regressions detected.")
        return

    new_count = sum(1 for r in regressions if r.status == "new")
    resolved_count = sum(1 for r in regressions if r.status == "resolved")
    changed_count = sum(1 for r in regressions if r.status == "changed")

    click.echo(
        f"Regressions: {new_count} new, "
        f"{resolved_count} resolved, "
        f"{changed_count} changed"
    )
    click.echo("")
    for reg in regressions:
        click.echo(f"  [{reg.status.upper()}] {reg.detail}")
