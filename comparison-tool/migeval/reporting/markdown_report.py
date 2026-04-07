"""Markdown report generation."""

from __future__ import annotations

from migeval.models import (
    AttemptResult,
    EvaluationRun,
    Issue,
    LayerName,
    Severity,
)

_SEVERITY_ORDER: list[Severity] = [
    "critical", "high", "medium", "low", "warning", "info",
]

_SEVERITY_ICON: dict[Severity, str] = {
    "critical": "!!!",
    "high": "!!",
    "medium": "!",
    "low": "~",
    "warning": "~",
    "info": "i",
}


def generate_markdown_report(run: EvaluationRun) -> str:
    """Generate a markdown report from an evaluation run."""
    lines: list[str] = []
    attempt_names = list(run.attempts.keys())

    lines.append("# Migration Evaluation Report")
    lines.append("")
    lines.append(f"**Target**: {run.target or 'unknown'}")
    lines.append(f"**Timestamp**: {run.timestamp}")
    lines.append("")

    # ── Summary dashboard ──
    lines.append("## Summary")
    lines.append("")

    # Overview table: before + each attempt side by side
    header = "| | Before |"
    separator = "|---|---:|"
    for name in attempt_names:
        header += f" {name} |"
        separator += "---:|"
    lines.append(header)
    lines.append(separator)

    # Build status row
    row = "| **Build** |"
    row += _build_cell(run.before) + " |"
    for name in attempt_names:
        row += _build_cell(run.attempts[name]) + " |"
    lines.append(row)

    # Total issues row
    row = "| **Total issues** |"
    row += f" {run.before.total_issues} |"
    for name in attempt_names:
        row += f" {run.attempts[name].total_issues} |"
    lines.append(row)

    # Per-severity rows
    for sev in _SEVERITY_ORDER:
        has_any = run.before.issues_by_severity.get(sev, 0) > 0
        for name in attempt_names:
            if run.attempts[name].issues_by_severity.get(sev, 0) > 0:
                has_any = True
        if not has_any:
            continue
        row = f"| {sev} |"
        row += f" {run.before.issues_by_severity.get(sev, 0)} |"
        for name in attempt_names:
            row += f" {run.attempts[name].issues_by_severity.get(sev, 0)} |"
        lines.append(row)

    # Per-layer issue count rows
    all_layers: list[LayerName] = ["source", "build", "runtime", "llm"]
    for layer in all_layers:
        before_lr = run.before.layer_results.get(layer)
        has_any = False
        counts: dict[str, str] = {}

        if before_lr and not before_lr.skipped:
            c = len(before_lr.issues)
            counts["before"] = str(c)
            if c > 0:
                has_any = True
        else:
            counts["before"] = "-"

        for name in attempt_names:
            lr = run.attempts[name].layer_results.get(layer)
            if lr and not lr.skipped:
                c = len(lr.issues)
                counts[name] = str(c)
                if c > 0:
                    has_any = True
            else:
                counts[name] = "-"

        row = f"| *{layer} layer* |"
        row += f" {counts['before']} |"
        for name in attempt_names:
            row += f" {counts[name]} |"
        lines.append(row)

    lines.append("")

    # ── Comparison deltas ──
    if run.before_vs_attempt:
        lines.append("## Comparisons")
        lines.append("")

        # Single table for all before-vs-attempt
        header = "| | " + " | ".join(
            f"before → {n}" for n in run.before_vs_attempt
        ) + " |"
        sep = "|---|" + "|".join(
            "---:" for _ in run.before_vs_attempt
        ) + "|"
        lines.append(header)
        lines.append(sep)

        for metric in ["Resolved", "New", "Shared", "Net"]:
            row = f"| **{metric}** |"
            for delta in run.before_vs_attempt.values():
                if metric == "Resolved":
                    row += f" {len(delta.resolved)} |"
                elif metric == "New":
                    row += f" {len(delta.new)} |"
                elif metric == "Shared":
                    row += f" {len(delta.shared)} |"
                elif metric == "Net":
                    row += f" **{delta.delta:+d}** |"
            lines.append(row)
        lines.append("")

    if run.attempt_vs_attempt:
        for key, delta in run.attempt_vs_attempt.items():
            label = key.replace("_vs_", " vs ")
            lines.append(f"### {label}")
            lines.append("")
            lines.append(
                f"| Resolved | New | Shared | Net |\n"
                f"|---:|---:|---:|---:|\n"
                f"| {len(delta.resolved)} | {len(delta.new)} "
                f"| {len(delta.shared)} | **{delta.delta:+d}** |"
            )
            lines.append("")

    # ── Detailed findings per attempt ──
    lines.append("---")
    lines.append("")
    lines.append("## Detailed Findings")
    lines.append("")

    # Before baseline
    lines.append("### Before (Baseline)")
    lines.append("")
    _append_attempt_details(lines, run.before)

    # Each attempt
    for name, attempt in run.attempts.items():
        lines.append(f"### Attempt: {name}")
        lines.append("")
        _append_attempt_details(lines, attempt)

    # ── Regressions ──
    if run.regressions:
        lines.append("---")
        lines.append("")
        lines.append("## Regressions (vs Previous Run)")
        lines.append("")
        new_count = sum(1 for r in run.regressions if r.status == "new")
        resolved_count = sum(
            1 for r in run.regressions if r.status == "resolved"
        )
        changed_count = sum(
            1 for r in run.regressions if r.status == "changed"
        )
        lines.append(
            f"| New | Resolved | Changed |\n"
            f"|---:|---:|---:|\n"
            f"| {new_count} | {resolved_count} | {changed_count} |"
        )
        lines.append("")
        for reg in run.regressions:
            lines.append(f"- **[{reg.status.upper()}]** {reg.detail}")
        lines.append("")

    return "\n".join(lines)


def _build_cell(attempt: AttemptResult) -> str:
    """Format a build status cell."""
    if attempt.build_passes is None:
        return " -"
    return " PASS" if attempt.build_passes else " **FAIL**"


def _append_attempt_details(
    lines: list[str], attempt: AttemptResult
) -> None:
    """Append detailed layer-by-layer findings for an attempt."""
    lines.append(f"`{attempt.path}`")
    lines.append("")

    for layer_name, lr in attempt.layer_results.items():
        if lr.skipped:
            lines.append(
                f"**{layer_name}** — skipped ({lr.skip_reason})"
            )
            lines.append("")
            continue

        if not lr.issues:
            lines.append(f"**{layer_name}** — no issues")
            lines.append("")
            continue

        # Group issues by severity
        by_severity: dict[Severity, list[Issue]] = {}
        for issue in lr.issues:
            by_severity.setdefault(issue.severity, []).append(issue)

        lines.append(
            f"**{layer_name}** — {len(lr.issues)} issues "
            f"({lr.duration_seconds}s)"
        )
        lines.append("")

        for sev in _SEVERITY_ORDER:
            issues = by_severity.get(sev, [])
            if not issues:
                continue

            for issue in issues:
                loc = ""
                if issue.file:
                    loc = f" `{issue.file}"
                    if issue.line:
                        loc += f":{issue.line}"
                    loc += "`"
                lines.append(
                    f"- [{_SEVERITY_ICON[sev]} {sev}] "
                    f"**{issue.title}**{loc}"
                )
                if issue.detail:
                    # Indent multi-line details
                    for dl in issue.detail.split("\n"):
                        lines.append(f"  > {dl}")
                if issue.suggestion:
                    lines.append(f"  > *Fix*: {issue.suggestion}")

        lines.append("")
