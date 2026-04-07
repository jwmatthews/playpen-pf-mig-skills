#!/usr/bin/env python3
"""
Generate a self-contained HTML evaluation report from evaluation-results.json.

Tabs:
  1. Value Story — elevator pitch: AI vs codemods grade delta, what AI got right/wrong
  2. Problem Areas — grouped by severity, plain-language descriptions, source-tagged
  3. Scorecard — pattern-by-pattern comparison table, color-coded, screenshot-able
  4. Evidence — collapsible per-file diffs and LLM debate transcripts

CLI: python3 generate_evaluation_report.py <work_dir> [--output path]
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pattern descriptions — maps IDs to plain-language explanations
# ---------------------------------------------------------------------------
PATTERN_DESCRIPTIONS: dict[str, str] = {
    "css-class-prefix": "CSS class prefixes were renamed (pf-v5- to pf-v6-). All selectors and class references need updating.",
    "utility-class-rename": "Utility CSS classes were renamed (pf-u-* to pf-v6-u-*).",
    "css-logical-properties": "CSS now uses logical properties (e.g. paddingInlineStart instead of paddingLeft) for better right-to-left language support.",
    "theme-dark-removal": "The dark theme variant was removed. Components using it must be updated.",
    "inner-ref-to-ref": "The innerRef prop was renamed to ref on components.",
    "align-right-to-end": "Alignment props changed from right/left to end/start for internationalization.",
    "is-action-cell": "The isActionCell prop was removed; use hasAction instead.",
    "space-items-removal": "The spaceItems prop was removed from components.",
    "ouia-component-id": "OUIA component IDs were standardized.",
    "chips-to-labels": "Chip/ChipGroup components were removed. Use Label/LabelGroup instead.",
    "split-button-items": "splitButtonOptions was renamed to splitButtonItems.",
    "modal-import-path": "Modal was moved to a new import path.",
    "text-content-consolidation": "TextContent, TextList, and Text were consolidated into a single Content component.",
    "empty-state-restructure": "EmptyState was restructured: EmptyStateHeader/EmptyStateIcon replaced with a titleText prop.",
    "toolbar-variant": "Toolbar variant values were renamed (e.g. chip-group to label-group).",
    "toolbar-gap": "Toolbar spacer props were replaced with CSS gap/columnGap/rowGap.",
    "button-icon-prop": "Button icon API changed to use an icon prop.",
    "page-section-variant": "PageSection variant='light'/'dark'/'darker' and PageSectionVariants enum were removed.",
    "page-masthead": "PageHeader was replaced with the Masthead component.",
    "react-tokens-icon-status": "React-tokens imports were renamed from global_* to t_* format.",
    "avatar-props": "Avatar component props were updated.",
    "select-rewrite": "The Select component was replaced with a new MenuToggle+SelectList pattern, requiring full restructuring.",
    "masthead-reorganization": "Masthead was reorganized: MastheadToggle removed, MastheadLogo added.",
    "test-selector-rewrite": "Test selectors changed from pf-v5- to pf-v6- CSS class prefixes.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def escape(text: Any) -> str:
    return html_mod.escape(str(text)) if text else ""


def grade_badge(grade: str, percent: int, size: str = "large") -> str:
    grade_colors: dict[str, tuple[str, str]] = {
        "A": ("#16a34a", "#dcfce7"),
        "B": ("#2563eb", "#dbeafe"),
        "C": ("#ca8a04", "#fef9c3"),
        "D": ("#ea580c", "#fff7ed"),
        "F": ("#dc2626", "#fee2e2"),
    }
    fg, bg = grade_colors.get(grade, ("#6b7280", "#f3f4f6"))
    if size == "large":
        return (
            f'<span style="display:inline-block;padding:8px 20px;border-radius:12px;'
            f'font-size:28px;font-weight:800;color:{fg};background:{bg}">'
            f'{grade} ({percent}%)</span>'
        )
    return (
        f'<span style="display:inline-block;padding:4px 12px;border-radius:8px;'
        f'font-size:16px;font-weight:700;color:{fg};background:{bg}">'
        f'{grade} ({percent}%)</span>'
    )


def severity_badge(severity: str) -> str:
    colors: dict[str, tuple[str, str]] = {
        "critical": ("#7f1d1d", "#fecaca"),
        "high": ("#dc2626", "#fee2e2"),
        "medium": ("#ea580c", "#fff7ed"),
        "low": ("#6b7280", "#f3f4f6"),
    }
    fg, bg = colors.get(severity, ("#6b7280", "#f3f4f6"))
    return f'<span class="badge" style="color:{fg};background:{bg}">{severity.upper()}</span>'


def status_badge(status: str) -> str:
    colors: dict[str, tuple[str, str]] = {
        "correct": ("#16a34a", "#dcfce7"),
        "incorrect": ("#dc2626", "#fee2e2"),
        "missing": ("#ea580c", "#fff7ed"),
        "file_missing": ("#9333ea", "#f3e8ff"),
        "not_migrated": ("#78716c", "#f5f5f4"),
        "not_applicable": ("#6b7280", "#f3f4f6"),
    }
    fg, bg = colors.get(status, ("#6b7280", "#f3f4f6"))
    label = status.replace("_", " ")
    return f'<span class="badge" style="color:{fg};background:{bg}">{label}</span>'


def source_badge(source: str) -> str:
    colors: dict[str, tuple[str, str]] = {
        "deterministic": ("#2563eb", "#dbeafe"),
        "adversarial": ("#7c3aed", "#ede9fe"),
    }
    label = "Detected by rules" if source == "deterministic" else "Detected by AI"
    fg, bg = colors.get(source, ("#6b7280", "#f3f4f6"))
    return f'<span class="badge" style="color:{fg};background:{bg}">{label}</span>'


def _pattern_description(pattern_id: str, scorecard: dict[str, Any] | None = None) -> str:
    """Get a human-readable description for a pattern ID."""
    # Check PATTERN_DESCRIPTIONS first
    desc = PATTERN_DESCRIPTIONS.get(pattern_id, "")
    if desc:
        return desc
    # Fall back to scorecard deterministic_findings
    if scorecard:
        for _name, attempt_data in scorecard.get("attempts", {}).items():
            for finding in attempt_data.get("deterministic_findings", []):
                if finding.get("id") == pattern_id and finding.get("description"):
                    return finding["description"]
    return ""


def _pattern_name(pattern_id: str) -> str:
    """Convert a pattern ID to a human-readable name."""
    return pattern_id.replace("-", " ").replace("_", " ").title()


def _build_diff_index(comparison_data: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Build index: attempt -> file_path -> text_diff from comparison data."""
    index: dict[str, dict[str, str]] = {}
    for attempt_name, comp_data in comparison_data.items():
        file_diffs: dict[str, str] = {}
        for f in comp_data.get("files", {}).get("modified", []):
            path = f.get("path", "")
            diff = f.get("text_diff", "")
            if path and diff:
                file_diffs[path] = diff
        index[attempt_name] = file_diffs
    return index


def _build_pattern_detail_index(
    pairwise_data: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Build index: attempt -> pattern_id -> [file details] from pairwise scoring data."""
    index: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for attempt_name, scoring in pairwise_data.items():
        by_pattern: dict[str, list[dict[str, Any]]] = {}
        for pr in scoring.get("pattern_results", []):
            pid = pr.get("pattern_id", "")
            details = pr.get("details", [])
            if pid and details:
                by_pattern[pid] = details
        index[attempt_name] = by_pattern
    return index


def _render_file_excerpt(
    file_path: str,
    diff_text: str,
    status: str = "",
    message: str = "",
    max_lines: int = 30,
) -> str:
    """Render a collapsible file excerpt with status badge and diff snippet."""
    parts: list[str] = []

    # Summary line with status badge
    status_html = status_badge(status) if status and status != "not_applicable" else ""
    msg_html = f' <span class="file-excerpt-msg">{escape(message)}</span>' if message else ""
    parts.append(f'<details class="file-excerpt">')
    parts.append(f'<summary><code>{escape(file_path)}</code> {status_html}{msg_html}</summary>')

    # Diff content (truncated)
    if diff_text:
        lines = diff_text.split("\n")
        truncated = len(lines) > max_lines
        if truncated:
            lines = lines[:max_lines]
        diff_html = _render_diff_snippet("\n".join(lines))
        parts.append(f'<div class="file-excerpt-diff">{diff_html}')
        if truncated:
            parts.append(f'<div class="file-excerpt-truncated">... {len(diff_text.split(chr(10))) - max_lines} more lines</div>')
        parts.append('</div>')
    else:
        parts.append('<div class="file-excerpt-no-diff">No diff available</div>')

    parts.append('</details>')
    return "\n".join(parts)


def _render_diff_snippet(diff_text: str) -> str:
    """Render a small diff snippet as styled HTML."""
    lines: list[str] = []
    for line in diff_text.split("\n"):
        escaped = escape(line)
        if line.startswith("---") or line.startswith("+++"):
            continue
        elif line.startswith("@@"):
            lines.append(f'<span class="diff-hunk">{escaped}</span>')
        elif line.startswith("-"):
            lines.append(f'<span class="diff-del">{escaped}</span>')
        elif line.startswith("+"):
            lines.append(f'<span class="diff-add">{escaped}</span>')
        else:
            lines.append(escaped)
    return f'<pre class="diff-pre">{"".join(lines)}</pre>'


def parse_unified_diff(diff_text: str) -> list[tuple[str, str, str]]:
    """Parse unified diff into list of (line_number, css_class, text) tuples."""
    result: list[tuple[str, str, str]] = []
    left_num = 0
    right_num = 0

    for line in diff_text.split("\n"):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)", line)
            if match:
                left_num = int(match.group(1)) - 1
            match2 = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            if match2:
                right_num = int(match2.group(1)) - 1
            result.append(("", "diff-hunk", line))
            continue
        if line.startswith("-"):
            left_num += 1
            result.append((str(left_num), "diff-del", line))
        elif line.startswith("+"):
            right_num += 1
            result.append((str(right_num), "diff-add", line))
        elif line.startswith(" ") or line == "":
            left_num += 1
            right_num += 1
            result.append((str(right_num), "", line[1:] if line.startswith(" ") else ""))

    return result


# ---------------------------------------------------------------------------
# Tab 1: Value Story
# ---------------------------------------------------------------------------

def render_value_story(
    data: dict[str, Any],
    scorecard: dict[str, Any] | None,
) -> str:
    attempt_scores = data.get("attempt_scores", {})
    comparisons = data.get("comparisons", {})
    parts: list[str] = []

    # Identify AI and codemods attempts
    attempt_names = sorted(attempt_scores.keys())
    ai_name = ""
    codemods_name = ""
    for n in attempt_names:
        nl = n.lower()
        if "codemod" in nl:
            codemods_name = n
        else:
            ai_name = n
    # Fallback: first two attempts
    if not ai_name and len(attempt_names) >= 1:
        ai_name = attempt_names[0]
    if not codemods_name and len(attempt_names) >= 2:
        codemods_name = attempt_names[1]

    ai_score = attempt_scores.get(ai_name, {})
    codemods_score = attempt_scores.get(codemods_name, {})

    ai_percent = ai_score.get("composite_percent", ai_score.get("overall_percent", 0))
    ai_grade = ai_score.get("composite_grade", ai_score.get("grade", "?"))
    ai_points = ai_score.get("composite_points", ai_score.get("points", 0))
    ai_pos = ai_score.get("positive_points", 0)
    ai_neg = ai_score.get("negative_points", 0)
    codemods_percent = codemods_score.get("composite_percent", codemods_score.get("overall_percent", 0))
    codemods_grade = codemods_score.get("composite_grade", codemods_score.get("grade", "?"))
    codemods_points = codemods_score.get("composite_points", codemods_score.get("points", 0))
    codemods_pos = codemods_score.get("positive_points", 0)
    codemods_neg = codemods_score.get("negative_points", 0)

    points_delta = ai_points - codemods_points

    # Hero banner — use points for the main comparison
    delta_color = "#16a34a" if points_delta > 0 else ("#dc2626" if points_delta < 0 else "#6b7280")
    delta_sign = "+" if points_delta > 0 else ""
    delta_word = "ahead" if points_delta > 0 else ("behind" if points_delta < 0 else "tied")

    if ai_name and codemods_name:
        parts.append(f'''<div class="hero-banner">
            <div class="hero-delta" style="color:{delta_color}">{delta_sign}{points_delta:.1f} pts</div>
            <div class="hero-subtitle">AI agent ({escape(ai_name)}) is
                <strong style="color:{delta_color}">{abs(points_delta):.1f} points {delta_word}</strong>
                vs codemods ({escape(codemods_name)})</div>
        </div>''')

    # Side-by-side grade cards with points
    parts.append('<div class="grade-comparison">')
    if ai_name:
        parts.append(f'''<div class="grade-card">
            <div class="grade-card-label">AI Agent</div>
            <div class="grade-card-name">{escape(ai_name)}</div>
            <div class="points-display"><span class="points-value">{ai_points:+.1f}</span> <span class="points-label">pts</span></div>
            <div class="points-breakdown">+{ai_pos:.1f} earned / {ai_neg:.1f} deducted</div>
            {grade_badge(ai_grade, ai_percent, "small")}
        </div>''')
    if codemods_name:
        parts.append(f'''<div class="grade-card">
            <div class="grade-card-label">Codemods</div>
            <div class="grade-card-name">{escape(codemods_name)}</div>
            <div class="points-display"><span class="points-value">{codemods_points:+.1f}</span> <span class="points-label">pts</span></div>
            <div class="points-breakdown">+{codemods_pos:.1f} earned / {codemods_neg:.1f} deducted</div>
            {grade_badge(codemods_grade, codemods_percent, "small")}
        </div>''')
    parts.append('</div>')

    # Build quadrant data from comparisons or scorecard
    ai_leads: list[dict[str, Any]] = []
    codemods_leads: list[dict[str, Any]] = []
    both_correct: list[dict[str, Any]] = []
    both_wrong: list[dict[str, Any]] = []

    if scorecard and scorecard.get("comparison"):
        comp_section = scorecard["comparison"]
        for item in comp_section.get("ai_leads_on", []):
            ai_leads.append(item)
        for item in comp_section.get("codemods_leads_on", []):
            codemods_leads.append(item)
        for item in comp_section.get("both_correct", []):
            both_correct.append(item)
        for item in comp_section.get("both_wrong", []):
            both_wrong.append(item)
    elif comparisons:
        for key, comp in comparisons.items():
            for adv in comp.get("a_advantages", []):
                ai_leads.append({"name": adv.get("name", ""), "id": adv.get("pattern_id", "")})
            for adv in comp.get("b_advantages", []):
                codemods_leads.append({"name": adv.get("name", ""), "id": adv.get("pattern_id", "")})
            for pid in comp.get("ties", []):
                both_correct.append({"name": _pattern_name(pid), "id": pid})
            for pid in comp.get("neither", []):
                both_wrong.append({"name": _pattern_name(pid), "id": pid})

    # What AI got right that codemods missed
    if ai_leads:
        parts.append('<div class="value-section value-positive">')
        parts.append(f'<h3>What AI Got Right That Codemods Missed ({len(ai_leads)})</h3>')
        parts.append('<ul class="value-list">')
        for item in ai_leads:
            pid = item.get("id", "")
            name = item.get("name") or _pattern_name(pid)
            desc = _pattern_description(pid, scorecard)
            parts.append(f'<li><strong>{escape(name)}</strong>')
            if desc:
                parts.append(f'<div class="value-desc">{escape(desc)}</div>')
            parts.append('</li>')
        parts.append('</ul></div>')

    # What AI got wrong (codemods leads + both wrong)
    ai_failures: list[dict[str, Any]] = []
    ai_failures.extend(codemods_leads)
    ai_failures.extend(both_wrong)

    if ai_failures:
        parts.append('<div class="value-section value-negative">')
        parts.append(f'<h3>Where AI Fell Short ({len(ai_failures)})</h3>')
        if codemods_leads:
            parts.append(f'<h4 class="value-subhead">Codemods got these right, AI did not ({len(codemods_leads)})</h4>')
            parts.append('<ul class="value-list">')
            for item in codemods_leads:
                pid = item.get("id", "")
                name = item.get("name") or _pattern_name(pid)
                desc = _pattern_description(pid, scorecard)
                parts.append(f'<li><strong>{escape(name)}</strong>')
                if desc:
                    parts.append(f'<div class="value-desc">{escape(desc)}</div>')
                parts.append('</li>')
            parts.append('</ul>')
        if both_wrong:
            parts.append(f'<h4 class="value-subhead">Neither got these right ({len(both_wrong)})</h4>')
            parts.append('<ul class="value-list">')
            for item in both_wrong:
                pid = item.get("id", "")
                name = item.get("name") or _pattern_name(pid)
                desc = _pattern_description(pid, scorecard)
                parts.append(f'<li><strong>{escape(name)}</strong>')
                if desc:
                    parts.append(f'<div class="value-desc">{escape(desc)}</div>')
                parts.append('</li>')
            parts.append('</ul>')
        parts.append('</div>')

    # Summary counts
    total = len(ai_leads) + len(codemods_leads) + len(both_correct) + len(both_wrong)
    if total > 0:
        parts.append('<div class="summary-stats">')
        parts.append(f'<div class="stat-box stat-green"><div class="stat-number">{len(both_correct)}</div>'
                     f'<div class="stat-label">Both Correct</div></div>')
        parts.append(f'<div class="stat-box stat-blue"><div class="stat-number">{len(ai_leads)}</div>'
                     f'<div class="stat-label">AI Leads</div></div>')
        parts.append(f'<div class="stat-box stat-purple"><div class="stat-number">{len(codemods_leads)}</div>'
                     f'<div class="stat-label">Codemods Leads</div></div>')
        parts.append(f'<div class="stat-box stat-red"><div class="stat-number">{len(both_wrong)}</div>'
                     f'<div class="stat-label">Both Wrong</div></div>')
        parts.append('</div>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tab 2: Problem Areas
# ---------------------------------------------------------------------------

def render_problem_areas(
    data: dict[str, Any],
    scorecard: dict[str, Any] | None,
    comparison_data: dict[str, dict[str, Any]] | None = None,
) -> str:
    problem_areas: list[dict[str, Any]] = data.get("problem_areas", [])

    # Also pull in LLM themes from scorecard
    llm_themes: list[dict[str, Any]] = []
    if scorecard:
        for attempt_name, attempt_data in scorecard.get("attempts", {}).items():
            for theme in attempt_data.get("llm_themes", []):
                llm_themes.append({**theme, "attempt": attempt_name, "source": "adversarial"})

    # Build diff index for file excerpts
    diff_index = _build_diff_index(comparison_data or {})
    pattern_detail_index = _build_pattern_detail_index(data.get("pairwise_data", {}))

    if not problem_areas and not llm_themes:
        return '<p class="muted">No problem areas identified.</p>'

    # Merge deterministic problems and LLM themes
    all_problems: list[dict[str, Any]] = []

    for pa in problem_areas:
        source = pa.get("source", "deterministic")
        all_problems.append({
            "severity": pa.get("severity", "medium"),
            "title": pa.get("description", "Unknown issue"),
            "description": pa.get("recommendation", ""),
            "files": pa.get("affected_files", []),
            "source": source,
            "attempt": pa.get("attempt", ""),
            "pattern_ids": pa.get("pattern_ids", []),
            "confidence": pa.get("referee_confidence"),
        })

    # Add LLM themes that aren't already covered
    existing_descriptions = {p["title"].lower() for p in all_problems}
    for theme in llm_themes:
        title = theme.get("theme", theme.get("description", ""))
        if title.lower() not in existing_descriptions:
            all_problems.append({
                "severity": theme.get("severity", "medium"),
                "title": title,
                "description": theme.get("description", ""),
                "files": theme.get("affected_files", []),
                "source": "adversarial",
                "attempt": theme.get("attempt", ""),
                "pattern_ids": [],
                "confidence": theme.get("confidence"),
            })

    parts: list[str] = []

    # Filter toolbar
    parts.append('<div class="filter-bar">')
    parts.append('<input type="text" class="filter-input" id="problem-search" '
                 'placeholder="Search problems..." onkeyup="filterProblems()">')
    parts.append('<select class="filter-input" id="problem-source-filter" onchange="filterProblems()">')
    parts.append('<option value="">All sources</option>')
    parts.append('<option value="deterministic">Rule-based detections</option>')
    parts.append('<option value="adversarial">AI-identified</option>')
    parts.append('</select>')
    parts.append('</div>')

    # Group by severity
    by_severity: dict[str, list[dict[str, Any]]] = {}
    for p in all_problems:
        sev = p.get("severity", "medium")
        by_severity.setdefault(sev, []).append(p)

    for sev in ["critical", "high", "medium", "low"]:
        items = by_severity.get(sev, [])
        if not items:
            continue

        parts.append(f'<h3>{severity_badge(sev)} {sev.title()} ({len(items)})</h3>')

        for p in items:
            title = escape(p.get("title", ""))
            desc = escape(p.get("description", ""))
            source = p.get("source", "deterministic")
            attempt = escape(p.get("attempt", ""))
            files = p.get("files", [])
            pattern_ids = p.get("pattern_ids", [])
            confidence = p.get("confidence")

            parts.append(f'<div class="problem-card" data-severity="{sev}" data-source="{source}">')

            # Header line with badges
            parts.append('<div class="problem-header">')
            parts.append(source_badge(source))
            if attempt:
                parts.append(f'<span class="badge" style="color:#475569;background:#f1f5f9">{attempt}</span>')
            if confidence is not None:
                parts.append(f'<span class="problem-confidence">Confidence: {confidence:.0%}</span>')
            parts.append('</div>')

            # Title and description
            parts.append(f'<div class="problem-title">{title}</div>')
            if desc and desc.lower() != title.lower():
                parts.append(f'<div class="problem-desc">{desc}</div>')

            # Pattern descriptions in plain language
            if pattern_ids:
                for pid in pattern_ids:
                    pdesc = _pattern_description(pid)
                    if pdesc:
                        parts.append(f'<div class="problem-pattern-desc">{escape(pdesc)}</div>')

            # What needs to change
            if pattern_ids:
                names = [_pattern_name(pid) for pid in pattern_ids]
                parts.append(f'<div class="problem-fix">Migration patterns involved: {", ".join(escape(n) for n in names)}</div>')

            # Affected files with excerpts
            if files:
                attempt_name = p.get("attempt", "")
                attempt_diffs = diff_index.get(attempt_name, {})
                # Get per-file pattern details if available
                file_statuses: dict[str, dict[str, str]] = {}
                for pid in pattern_ids:
                    for detail in pattern_detail_index.get(attempt_name, {}).get(pid, []):
                        fp = detail.get("file", "")
                        if fp:
                            file_statuses[fp] = {
                                "status": detail.get("status", ""),
                                "message": detail.get("message", ""),
                            }

                parts.append(f'<details class="problem-files"><summary>Affected files ({len(files)})</summary>')
                parts.append('<div class="problem-files-list">')
                for f in files[:20]:
                    diff_text = attempt_diffs.get(f, "")
                    fs = file_statuses.get(f, {})
                    parts.append(_render_file_excerpt(
                        f, diff_text,
                        status=fs.get("status", ""),
                        message=fs.get("message", ""),
                    ))
                if len(files) > 20:
                    parts.append(f'<div class="muted">... and {len(files) - 20} more files</div>')
                parts.append('</div></details>')

            parts.append('</div>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tab 3: Scorecard
# ---------------------------------------------------------------------------

def render_scorecard(
    data: dict[str, Any],
    scorecard: dict[str, Any] | None,
    comparison_data: dict[str, dict[str, Any]] | None = None,
) -> str:
    parts: list[str] = []
    attempt_scores = data.get("attempt_scores", {})
    attempt_names = sorted(attempt_scores.keys())

    if not attempt_names:
        return '<p class="muted">No scoring data available.</p>'

    # Build diff and pattern detail indexes for file excerpts
    diff_index = _build_diff_index(comparison_data or {})
    pattern_detail_index = _build_pattern_detail_index(data.get("pairwise_data", {}))

    # Identify AI vs codemods
    ai_name = ""
    codemods_name = ""
    for n in attempt_names:
        nl = n.lower()
        if "codemod" in nl:
            codemods_name = n
        else:
            ai_name = n
    if not ai_name and len(attempt_names) >= 1:
        ai_name = attempt_names[0]
    if not codemods_name and len(attempt_names) >= 2:
        codemods_name = attempt_names[1]

    # Build per-pattern data from scorecard or pairwise_data
    pattern_rows: list[dict[str, Any]] = []
    seen_patterns: set[str] = set()

    # Primary source: scorecard.json deterministic_findings
    if scorecard:
        for attempt_name, attempt_data in scorecard.get("attempts", {}).items():
            for finding in attempt_data.get("deterministic_findings", []):
                pid = finding.get("id", "")
                if pid in seen_patterns:
                    # Update existing row with this attempt's status
                    for row in pattern_rows:
                        if row["id"] == pid:
                            row["statuses"][attempt_name] = finding.get("status", "unknown")
                            row.setdefault("files", {})[attempt_name] = finding.get("files", [])
                    continue
                seen_patterns.add(pid)
                row: dict[str, Any] = {
                    "id": pid,
                    "name": finding.get("name") or _pattern_name(pid),
                    "description": finding.get("description") or _pattern_description(pid, scorecard),
                    "complexity": finding.get("complexity", "moderate"),
                    "statuses": {attempt_name: finding.get("status", "unknown")},
                    "files": {attempt_name: finding.get("files", [])},
                }
                pattern_rows.append(row)

    # Fill in statuses from pairwise_data for any missing attempt columns
    pairwise_data = data.get("pairwise_data", {})
    for attempt_name, scoring in pairwise_data.items():
        for pr in scoring.get("pattern_results", []):
            pid = pr.get("pattern_id", "")
            status = pr.get("status", "not_applicable")
            if status == "not_applicable":
                continue
            if pid not in seen_patterns:
                seen_patterns.add(pid)
                pattern_rows.append({
                    "id": pid,
                    "name": pr.get("name") or _pattern_name(pid),
                    "description": _pattern_description(pid, scorecard),
                    "complexity": pr.get("complexity", "moderate"),
                    "statuses": {attempt_name: status},
                    "files": {attempt_name: pr.get("files", [])},
                })
            else:
                for row in pattern_rows:
                    if row["id"] == pid:
                        if attempt_name not in row["statuses"]:
                            row["statuses"][attempt_name] = status
                        row.setdefault("files", {})[attempt_name] = pr.get("files", [])

    if not pattern_rows:
        return '<p class="muted">No pattern data available for scorecard.</p>'

    # Classify into quadrants
    quadrants: dict[str, list[dict[str, Any]]] = {
        "both_correct": [],
        "ai_leads": [],
        "codemods_leads": [],
        "both_wrong": [],
    }

    for row in pattern_rows:
        ai_status = row["statuses"].get(ai_name, "missing")
        cm_status = row["statuses"].get(codemods_name, "missing")
        ai_ok = ai_status == "correct"
        cm_ok = cm_status == "correct"

        if ai_ok and cm_ok:
            quadrants["both_correct"].append(row)
        elif ai_ok and not cm_ok:
            quadrants["ai_leads"].append(row)
        elif not ai_ok and cm_ok:
            quadrants["codemods_leads"].append(row)
        else:
            quadrants["both_wrong"].append(row)

    # Quadrant summary cards
    parts.append('<div class="quadrant-grid">')
    parts.append(f'''<div class="quadrant-card quadrant-green">
        <div class="quadrant-count">{len(quadrants["both_correct"])}</div>
        <div class="quadrant-label">Both Correct</div>
    </div>''')
    parts.append(f'''<div class="quadrant-card quadrant-blue">
        <div class="quadrant-count">{len(quadrants["ai_leads"])}</div>
        <div class="quadrant-label">AI Leads</div>
    </div>''')
    parts.append(f'''<div class="quadrant-card quadrant-purple">
        <div class="quadrant-count">{len(quadrants["codemods_leads"])}</div>
        <div class="quadrant-label">Codemods Leads</div>
    </div>''')
    parts.append(f'''<div class="quadrant-card quadrant-red">
        <div class="quadrant-count">{len(quadrants["both_wrong"])}</div>
        <div class="quadrant-label">Both Wrong</div>
    </div>''')
    parts.append('</div>')

    # Filter
    parts.append('<div class="filter-bar">')
    parts.append('<input type="text" class="filter-input" id="scorecard-search" '
                 'placeholder="Search patterns..." onkeyup="filterScorecard()">')
    parts.append('<select class="filter-input" id="scorecard-quadrant" onchange="filterScorecard()">')
    parts.append('<option value="">All quadrants</option>')
    parts.append('<option value="both_correct">Both Correct</option>')
    parts.append('<option value="ai_leads">AI Leads</option>')
    parts.append('<option value="codemods_leads">Codemods Leads</option>')
    parts.append('<option value="both_wrong">Both Wrong</option>')
    parts.append('</select>')
    parts.append('</div>')

    # Main comparison table
    complexity_colors: dict[str, tuple[str, str]] = {
        "trivial": ("#6b7280", "#f3f4f6"),
        "moderate": ("#b45309", "#fef3c7"),
        "complex": ("#dc2626", "#fee2e2"),
    }

    parts.append('<table id="scorecard-table"><thead><tr>')
    parts.append('<th style="width:30%">Pattern</th>')
    parts.append('<th style="width:30%">Description</th>')
    parts.append('<th>Complexity</th>')
    if ai_name:
        parts.append(f'<th>AI ({escape(ai_name)})</th>')
    if codemods_name:
        parts.append(f'<th>Codemods ({escape(codemods_name)})</th>')
    parts.append('</tr></thead><tbody>')

    col_count = 3 + (1 if ai_name else 0) + (1 if codemods_name else 0)

    for row_idx, row in enumerate(pattern_rows):
        ai_status = row["statuses"].get(ai_name, "missing")
        cm_status = row["statuses"].get(codemods_name, "missing")
        ai_ok = ai_status == "correct"
        cm_ok = cm_status == "correct"

        if ai_ok and cm_ok:
            quadrant = "both_correct"
        elif ai_ok and not cm_ok:
            quadrant = "ai_leads"
        elif not ai_ok and cm_ok:
            quadrant = "codemods_leads"
        else:
            quadrant = "both_wrong"

        name = escape(row["name"])
        desc = escape(row["description"])
        complexity = row["complexity"]
        c_fg, c_bg = complexity_colors.get(complexity, ("#6b7280", "#f3f4f6"))
        pid = row["id"]
        row_files = row.get("files", {})

        # Collect all unique files across attempts for this pattern
        all_files: list[str] = []
        seen_files: set[str] = set()
        for attempt_name_iter in attempt_names:
            for fp in row_files.get(attempt_name_iter, []):
                if fp not in seen_files:
                    seen_files.add(fp)
                    all_files.append(fp)

        has_files = len(all_files) > 0

        parts.append(f'<tr data-quadrant="{quadrant}" '
                     f'data-search="{name.lower()} {desc.lower()}" '
                     f'class="scorecard-row{" has-files" if has_files else ""}" '
                     f'{"onclick=\"toggleScorecardFiles(this)\" style=\"cursor:pointer\"" if has_files else ""}'
                     f'>')
        parts.append(f'<td><strong>{name}</strong>'
                     f'{" <span class=\"file-count-hint\">(" + str(len(all_files)) + " files)</span>" if has_files else ""}'
                     f'</td>')
        parts.append(f'<td class="desc-cell">{desc}</td>')
        parts.append(f'<td><span class="badge" style="color:{c_fg};background:{c_bg}">{complexity}</span></td>')
        if ai_name:
            parts.append(f'<td>{status_badge(ai_status)}</td>')
        if codemods_name:
            parts.append(f'<td>{status_badge(cm_status)}</td>')
        parts.append('</tr>')

        # File details row (hidden by default)
        if has_files:
            parts.append(f'<tr class="scorecard-files-row" style="display:none" data-quadrant="{quadrant}" '
                         f'data-search="{name.lower()} {desc.lower()}">')
            parts.append(f'<td colspan="{col_count}" class="scorecard-files-cell">')

            for attempt_name_iter in attempt_names:
                attempt_files = row_files.get(attempt_name_iter, [])
                if not attempt_files:
                    continue
                attempt_diffs = diff_index.get(attempt_name_iter, {})
                attempt_details = pattern_detail_index.get(attempt_name_iter, {}).get(pid, [])
                detail_by_file = {d.get("file", ""): d for d in attempt_details}

                if len(attempt_names) > 1:
                    parts.append(f'<div class="scorecard-attempt-label">{escape(attempt_name_iter)}</div>')

                for fp in attempt_files:
                    diff_text = attempt_diffs.get(fp, "")
                    detail = detail_by_file.get(fp, {})
                    parts.append(_render_file_excerpt(
                        fp, diff_text,
                        status=detail.get("status", ""),
                        message=detail.get("message", ""),
                    ))

            parts.append('</td></tr>')

    parts.append('</tbody></table>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tab 4: Evidence
# ---------------------------------------------------------------------------

def render_evidence(
    data: dict[str, Any],
    comparison_data: dict[str, dict[str, Any]],
    llm_assessment: dict[str, Any] | None,
    work_dir: Path | None,
) -> str:
    parts: list[str] = []
    diff_index = _build_diff_index(comparison_data)
    pairwise_data = data.get("pairwise_data", {})

    # Section 1: Per-file diffs
    parts.append('<h3>Per-File Diffs</h3>')

    has_diffs = False
    for attempt_name in sorted(diff_index.keys()):
        attempt_diffs = diff_index[attempt_name]
        if not attempt_diffs:
            continue
        has_diffs = True

        parts.append(f'<h4>{escape(attempt_name)} ({len(attempt_diffs)} files)</h4>')
        parts.append(f'<div class="filter-bar">')
        parts.append(f'<input type="text" class="filter-input evidence-file-search" '
                     f'data-attempt="{escape(attempt_name)}" '
                     f'placeholder="Search files..." onkeyup="filterEvidenceFiles(this)">')
        parts.append('</div>')

        parts.append(f'<div class="evidence-file-list" data-attempt="{escape(attempt_name)}">')

        for file_path in sorted(attempt_diffs.keys()):
            diff_text = attempt_diffs[file_path]
            diff_size = len(diff_text.encode("utf-8", errors="replace"))

            parts.append(f'<details class="evidence-file-item" data-filepath="{escape(file_path).lower()}">')
            parts.append(f'<summary><code>{escape(file_path)}</code>'
                         f' <span class="muted">({diff_size // 1024}KB)</span></summary>')

            if diff_size > 50 * 1024:
                parts.append(f'<div class="evidence-too-large">File diff too large to display inline ({diff_size // 1024}KB)</div>')
            else:
                parsed = parse_unified_diff(diff_text)
                truncated = False
                if len(parsed) > 300:
                    parsed = parsed[:300]
                    truncated = True

                diff_lines: list[str] = []
                for _line_num, css_class, text in parsed:
                    escaped_text = escape(text)
                    if css_class:
                        diff_lines.append(f'<span class="{css_class}">{escaped_text}</span>')
                    else:
                        diff_lines.append(escaped_text)

                parts.append(f'<pre class="diff-pre">{"".join(diff_lines)}</pre>')
                if truncated:
                    parts.append('<p class="muted" style="padding:4px 8px;font-size:12px">(truncated at 300 lines)</p>')

            parts.append('</details>')

        parts.append('</div>')

    if not has_diffs:
        parts.append('<p class="muted">No file diffs available.</p>')

    # Section 2: LLM Review Debate Transcripts
    parts.append('<h3 style="margin-top:32px">LLM Review Debate Transcripts</h3>')
    parts.append('<p class="evidence-intro">The AI review uses a multi-round debate process: '
                 'a <strong>Critic</strong> identifies potential issues, a <strong>Challenger</strong> '
                 'argues against false positives, and a <strong>Judge</strong> makes the final ruling.</p>')

    has_debates = False
    if work_dir:
        llm_review_dir = work_dir / "llm-review"
        if llm_review_dir.is_dir():
            for attempt_dir in sorted(llm_review_dir.iterdir()):
                if not attempt_dir.is_dir():
                    continue
                attempt_name = attempt_dir.name

                # Collect rounds
                rounds: list[dict[str, Any]] = []
                round_nums: set[int] = set()
                for f in sorted(attempt_dir.iterdir()):
                    match = re.match(r"round-(\d+)-(critic|challenger|judge)\.json", f.name)
                    if match:
                        round_nums.add(int(match.group(1)))

                for round_num in sorted(round_nums):
                    round_data: dict[str, Any] = {"round": round_num}
                    for role in ["critic", "challenger", "judge"]:
                        role_path = attempt_dir / f"round-{round_num}-{role}.json"
                        if role_path.exists():
                            try:
                                with open(role_path, "r", encoding="utf-8") as f:
                                    round_data[role] = json.load(f)
                            except (json.JSONDecodeError, OSError):
                                pass
                    rounds.append(round_data)

                if not rounds:
                    continue
                has_debates = True

                parts.append(f'<h4>{escape(attempt_name)} ({len(rounds)} round{"s" if len(rounds) != 1 else ""})</h4>')

                for rd in rounds:
                    round_num = rd["round"]
                    parts.append(f'<details class="debate-round">')
                    parts.append(f'<summary>Round {round_num}</summary>')
                    parts.append('<div class="debate-content">')

                    for role, role_label, role_color in [
                        ("critic", "Critic", "#dc2626"),
                        ("challenger", "Challenger", "#2563eb"),
                        ("judge", "Judge", "#7c3aed"),
                    ]:
                        role_data = rd.get(role)
                        if not role_data:
                            continue

                        parts.append(f'<div class="debate-role">')
                        parts.append(f'<div class="debate-role-header" style="color:{role_color}">{role_label}</div>')

                        # Render role data - handle both string and structured formats
                        if isinstance(role_data, str):
                            parts.append(f'<div class="debate-role-body"><pre class="debate-text">{escape(role_data)}</pre></div>')
                        elif isinstance(role_data, dict):
                            # Common fields to show
                            reasoning = role_data.get("reasoning", role_data.get("analysis", ""))
                            findings = role_data.get("findings", role_data.get("issues", []))
                            verdict = role_data.get("verdict", role_data.get("decision", ""))
                            confidence = role_data.get("confidence")

                            if reasoning:
                                r_text = reasoning if isinstance(reasoning, str) else json.dumps(reasoning, indent=2)
                                parts.append(f'<div class="debate-reasoning"><strong>Reasoning:</strong> {escape(r_text)}</div>')
                            if verdict:
                                parts.append(f'<div class="debate-verdict"><strong>Verdict:</strong> {escape(str(verdict))}</div>')
                            if confidence is not None:
                                parts.append(f'<div class="debate-confidence"><strong>Confidence:</strong> {confidence}</div>')
                            if findings and isinstance(findings, list):
                                parts.append('<div class="debate-findings"><strong>Findings:</strong><ul>')
                                for finding in findings[:20]:
                                    if isinstance(finding, dict):
                                        f_desc = finding.get("description", finding.get("issue", str(finding)))
                                        parts.append(f'<li>{escape(str(f_desc))}</li>')
                                    else:
                                        parts.append(f'<li>{escape(str(finding))}</li>')
                                parts.append('</ul></div>')
                        else:
                            parts.append(f'<div class="debate-role-body"><pre class="debate-text">{escape(json.dumps(role_data, indent=2))}</pre></div>')

                        parts.append('</div>')

                    parts.append('</div></details>')

    if not has_debates:
        parts.append('<p class="muted">No debate transcripts found. '
                     'Look for llm-review/&lt;attempt&gt;/round-*-{critic,challenger,judge}.json files.</p>')

    # Section 3: LLM Assessment per-file details (from llm-assessment.json)
    if llm_assessment:
        file_assessments = llm_assessment.get("file_assessments", [])
        if file_assessments:
            parts.append('<h3 style="margin-top:32px">LLM File-Level Assessments</h3>')
            sorted_files = sorted(file_assessments, key=lambda x: x.get("summary_score", 1.0))

            for fa in sorted_files:
                file_path = fa.get("file", "")
                attempt = fa.get("attempt", "")
                issues = fa.get("issues", [])
                file_score = fa.get("summary_score", 1.0)
                score_color = "#16a34a" if file_score >= 0.8 else ("#ea580c" if file_score >= 0.6 else "#dc2626")

                parts.append(f'<details class="evidence-file-item">')
                parts.append(f'<summary><code>{escape(file_path)}</code> '
                             f'<span class="badge" style="color:#475569;background:#f1f5f9">{escape(attempt)}</span> '
                             f'<span style="color:{score_color};font-weight:600">{file_score:.0%}</span> '
                             f'<span class="muted">{len(issues)} issue{"s" if len(issues) != 1 else ""}</span></summary>')

                if issues:
                    parts.append('<table><thead><tr>')
                    parts.append('<th>Severity</th><th>Description</th><th>Impact</th><th>Verdict</th><th>Confidence</th>')
                    parts.append('</tr></thead><tbody>')
                    for issue in issues:
                        i_sev = issue.get("severity", "medium")
                        i_desc = escape(issue.get("description", ""))
                        i_impact = issue.get("impact_score", 0)
                        i_verdict = issue.get("referee_verdict", "")
                        i_conf = issue.get("referee_confidence")
                        conf_str = f"{i_conf:.0%}" if i_conf is not None else "--"
                        parts.append(f'<tr><td>{severity_badge(i_sev)}</td>')
                        parts.append(f'<td style="font-size:13px">{i_desc}</td>')
                        parts.append(f'<td style="text-align:center">{i_impact}</td>')
                        parts.append(f'<td>{status_badge(i_verdict) if i_verdict else "--"}</td>')
                        parts.append(f'<td>{conf_str}</td></tr>')
                    parts.append('</tbody></table>')

                parts.append('</details>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main HTML generation
# ---------------------------------------------------------------------------

def generate_html(
    data: dict[str, Any],
    comparison_data: dict[str, dict[str, Any]] | None = None,
    llm_assessment: dict[str, Any] | None = None,
    scorecard: dict[str, Any] | None = None,
    work_dir: Path | None = None,
) -> str:
    if comparison_data is None:
        comparison_data = {}
    if scorecard is None:
        scorecard = {}

    metadata = data.get("metadata", {})
    attempt_scores = data.get("attempt_scores", {})
    target = metadata.get("target", "")
    timestamp = metadata.get("timestamp", datetime.now().isoformat())

    try:
        ts_display = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts_display = timestamp

    attempt_names = sorted(attempt_scores.keys())
    header_attempts = " vs ".join(attempt_names)

    value_html = render_value_story(data, scorecard)
    problems_html = render_problem_areas(data, scorecard, comparison_data)
    scorecard_html = render_scorecard(data, scorecard, comparison_data)
    evidence_html = render_evidence(data, comparison_data, llm_assessment, work_dir)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Migration Evaluation - {escape(header_attempts)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1f2937; background: #f9fafb; line-height: 1.6; }}
  .container {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}

  /* Header */
  header {{ background: linear-gradient(135deg, #1e293b 0%, #334155 100%); color: white; padding: 36px 32px; margin: -24px -24px 32px; }}
  header h1 {{ font-size: 26px; margin-bottom: 8px; letter-spacing: -0.5px; }}
  .header-meta {{ display: flex; gap: 24px; flex-wrap: wrap; font-size: 14px; color: #94a3b8; }}

  /* Badges */
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; white-space: nowrap; }}

  /* Tabs */
  .tabs {{ display: flex; gap: 0; border-bottom: 2px solid #e2e8f0; margin-bottom: 28px; overflow-x: auto; }}
  .tab {{ background: none; border: none; padding: 14px 28px; cursor: pointer; font-size: 14px; font-weight: 600; color: #64748b; border-bottom: 3px solid transparent; margin-bottom: -2px; white-space: nowrap; transition: color 0.15s, border-color 0.15s; }}
  .tab:hover {{ color: #1e293b; }}
  .tab.active {{ color: #2563eb; border-bottom-color: #2563eb; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  /* Hero banner (Value Story) */
  .hero-banner {{ text-align: center; padding: 36px 24px; background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 28px; }}
  .hero-delta {{ font-size: 48px; font-weight: 800; letter-spacing: -2px; }}
  .hero-subtitle {{ font-size: 18px; color: #475569; margin-top: 8px; }}

  /* Grade comparison cards */
  .grade-comparison {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 28px; }}
  .grade-card {{ background: white; border-radius: 12px; padding: 28px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .grade-card-label {{ font-size: 13px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .grade-card-name {{ font-size: 15px; color: #475569; margin-bottom: 12px; }}

  /* Points display */
  .points-display {{ margin: 8px 0; }}
  .points-value {{ font-size: 36px; font-weight: 800; letter-spacing: -1px; }}
  .points-label {{ font-size: 18px; color: #64748b; font-weight: 600; }}
  .points-breakdown {{ font-size: 12px; color: #94a3b8; margin-bottom: 12px; }}

  /* Value sections */
  .value-section {{ background: white; border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .value-positive {{ border-left: 4px solid #16a34a; }}
  .value-negative {{ border-left: 4px solid #dc2626; }}
  .value-list {{ margin: 12px 0 0 20px; }}
  .value-list li {{ margin-bottom: 10px; font-size: 15px; }}
  .value-desc {{ font-size: 13px; color: #64748b; margin-top: 2px; }}
  .value-subhead {{ font-size: 14px; color: #64748b; margin: 16px 0 8px; font-weight: 600; }}

  /* Summary stats */
  .summary-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 24px; }}
  .stat-box {{ text-align: center; padding: 20px 12px; border-radius: 10px; }}
  .stat-green {{ background: #dcfce7; }}
  .stat-blue {{ background: #dbeafe; }}
  .stat-purple {{ background: #ede9fe; }}
  .stat-red {{ background: #fee2e2; }}
  .stat-number {{ font-size: 32px; font-weight: 800; }}
  .stat-green .stat-number {{ color: #16a34a; }}
  .stat-blue .stat-number {{ color: #2563eb; }}
  .stat-purple .stat-number {{ color: #7c3aed; }}
  .stat-red .stat-number {{ color: #dc2626; }}
  .stat-label {{ font-size: 13px; color: #64748b; font-weight: 600; margin-top: 4px; }}

  /* Problem Areas */
  .problem-card {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .problem-header {{ display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }}
  .problem-confidence {{ font-size: 12px; color: #64748b; }}
  .problem-title {{ font-size: 15px; font-weight: 600; color: #1e293b; margin-bottom: 6px; }}
  .problem-desc {{ font-size: 14px; color: #475569; margin-bottom: 8px; }}
  .problem-pattern-desc {{ font-size: 13px; color: #64748b; background: #f8fafc; padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid #e2e8f0; }}
  .problem-fix {{ font-size: 13px; color: #475569; margin-bottom: 8px; }}
  .problem-files {{ margin-top: 8px; }}
  .problem-files summary {{ cursor: pointer; font-size: 13px; color: #2563eb; }}
  .problem-files ul {{ margin: 8px 0 0 20px; }}
  .problem-files li {{ font-size: 13px; margin-bottom: 2px; }}

  /* Quadrant grid (Scorecard) */
  .quadrant-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }}
  .quadrant-card {{ text-align: center; padding: 20px 12px; border-radius: 10px; }}
  .quadrant-green {{ background: #dcfce7; }}
  .quadrant-blue {{ background: #dbeafe; }}
  .quadrant-purple {{ background: #ede9fe; }}
  .quadrant-red {{ background: #fee2e2; }}
  .quadrant-count {{ font-size: 36px; font-weight: 800; }}
  .quadrant-green .quadrant-count {{ color: #16a34a; }}
  .quadrant-blue .quadrant-count {{ color: #2563eb; }}
  .quadrant-purple .quadrant-count {{ color: #7c3aed; }}
  .quadrant-red .quadrant-count {{ color: #dc2626; }}
  .quadrant-label {{ font-size: 13px; font-weight: 600; color: #64748b; margin-top: 4px; }}

  /* Tables */
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  th {{ background: #f8fafc; text-align: left; padding: 12px 16px; font-size: 13px; font-weight: 600; color: #475569; border-bottom: 2px solid #e2e8f0; }}
  td {{ padding: 12px 16px; font-size: 14px; border-bottom: 1px solid #f1f5f9; }}
  .desc-cell {{ font-size: 13px; color: #64748b; max-width: 300px; }}

  /* Filter bar */
  .filter-bar {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }}
  .filter-input {{ padding: 8px 14px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; background: white; }}
  .filter-input:focus {{ outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }}

  /* Evidence */
  .evidence-file-item {{ background: white; border-radius: 10px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); overflow: hidden; }}
  .evidence-file-item summary {{ cursor: pointer; padding: 12px 16px; font-size: 14px; list-style: none; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
  .evidence-file-item summary::-webkit-details-marker {{ display: none; }}
  .evidence-file-item summary::before {{ content: "\\25B6"; font-size: 10px; color: #94a3b8; margin-right: 4px; transition: transform 0.15s; }}
  .evidence-file-item[open] summary::before {{ transform: rotate(90deg); }}
  .evidence-too-large {{ padding: 16px; color: #64748b; font-size: 13px; font-style: italic; }}
  .evidence-intro {{ font-size: 14px; color: #64748b; margin-bottom: 20px; }}

  /* Debate */
  .debate-round {{ background: white; border-radius: 10px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); overflow: hidden; }}
  .debate-round summary {{ cursor: pointer; padding: 12px 16px; font-size: 14px; font-weight: 600; list-style: none; }}
  .debate-round summary::-webkit-details-marker {{ display: none; }}
  .debate-round summary::before {{ content: "\\25B6"; font-size: 10px; color: #94a3b8; margin-right: 8px; transition: transform 0.15s; }}
  .debate-round[open] summary::before {{ transform: rotate(90deg); }}
  .debate-content {{ padding: 0 16px 16px; }}
  .debate-role {{ margin-bottom: 16px; padding: 14px; background: #f8fafc; border-radius: 8px; }}
  .debate-role-header {{ font-size: 14px; font-weight: 700; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .debate-reasoning, .debate-verdict, .debate-confidence, .debate-findings {{ font-size: 13px; color: #475569; margin-bottom: 6px; }}
  .debate-findings ul {{ margin: 6px 0 0 20px; }}
  .debate-findings li {{ margin-bottom: 4px; }}
  .debate-text {{ font-size: 12px; white-space: pre-wrap; word-break: break-word; color: #475569; background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; }}

  /* Diff styling */
  .diff-add {{ background: #dcfce7; display: block; }}
  .diff-del {{ background: #fee2e2; display: block; }}
  .diff-hunk {{ background: #dbeafe; color: #2563eb; display: block; font-weight: 500; }}
  .diff-pre {{ font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace; font-size: 12px; line-height: 1.5; overflow-x: auto; padding: 10px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; white-space: pre-wrap; word-break: break-all; margin: 8px 12px 12px; }}

  /* File excerpts */
  .file-excerpt {{ background: #f8fafc; border-radius: 8px; margin-bottom: 6px; border: 1px solid #e2e8f0; }}
  .file-excerpt summary {{ cursor: pointer; padding: 8px 12px; font-size: 13px; list-style: none; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .file-excerpt summary::-webkit-details-marker {{ display: none; }}
  .file-excerpt summary::before {{ content: "\\25B6"; font-size: 9px; color: #94a3b8; transition: transform 0.15s; }}
  .file-excerpt[open] summary::before {{ transform: rotate(90deg); }}
  .file-excerpt-msg {{ color: #64748b; font-size: 12px; }}
  .file-excerpt-diff {{ padding: 0 8px 8px; }}
  .file-excerpt-diff .diff-pre {{ margin: 4px 0 0; font-size: 11px; line-height: 1.4; max-height: 300px; overflow-y: auto; }}
  .file-excerpt-no-diff {{ padding: 8px 12px; color: #94a3b8; font-size: 12px; font-style: italic; }}
  .file-excerpt-truncated {{ padding: 4px 12px; color: #94a3b8; font-size: 11px; font-style: italic; }}
  .problem-files-list {{ padding: 8px 0; }}

  /* Scorecard file rows */
  .scorecard-row.has-files td {{ cursor: pointer; }}
  .scorecard-row.has-files td:first-child strong::after {{ content: ""; }}
  .file-count-hint {{ font-size: 11px; color: #94a3b8; font-weight: 400; }}
  .scorecard-files-cell {{ padding: 8px 16px 16px !important; background: #f8fafc; }}
  .scorecard-attempt-label {{ font-size: 12px; font-weight: 600; color: #475569; margin: 8px 0 4px; text-transform: uppercase; letter-spacing: 0.5px; }}

  /* General */
  code {{ background: #f1f5f9; padding: 1px 6px; border-radius: 4px; font-size: 13px; }}
  h3 {{ font-size: 18px; margin-bottom: 14px; color: #1e293b; }}
  h4 {{ font-size: 15px; margin-bottom: 10px; color: #334155; }}
  .muted {{ color: #94a3b8; font-style: italic; }}

  @media (max-width: 768px) {{
    .grade-comparison {{ grid-template-columns: 1fr; }}
    .summary-stats, .quadrant-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}

  @media print {{
    body {{ background: white; }}
    .container {{ max-width: none; padding: 0; }}
    header {{ background: #1e293b !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .tab-content {{ display: block !important; page-break-inside: avoid; }}
    .tabs {{ display: none; }}
    .tab-content::before {{ content: attr(data-title); display: block; font-size: 20px; font-weight: 700; margin: 24px 0 12px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Migration Evaluation Report</h1>
    <div class="header-meta">
      <span>{escape(header_attempts)}</span>
      {f'<span>Target: {escape(target)}</span>' if target else ''}
      <span>{ts_display}</span>
    </div>
  </header>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('value')">Value Story</button>
    <button class="tab" onclick="switchTab('problems')">Problem Areas</button>
    <button class="tab" onclick="switchTab('scorecard')">Scorecard</button>
    <button class="tab" onclick="switchTab('evidence')">Evidence</button>
  </div>

  <div id="value" class="tab-content active" data-title="Value Story">
    {value_html}
  </div>

  <div id="problems" class="tab-content" data-title="Problem Areas">
    {problems_html}
  </div>

  <div id="scorecard" class="tab-content" data-title="Scorecard">
    {scorecard_html}
  </div>

  <div id="evidence" class="tab-content" data-title="Evidence">
    {evidence_html}
  </div>
</div>

<script>
function switchTab(id) {{
  document.querySelectorAll('.tab-content').forEach(function(el) {{ el.classList.remove('active'); }});
  document.querySelectorAll('.tab').forEach(function(el) {{ el.classList.remove('active'); }});
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
}}

/* Problem Areas filtering */
function filterProblems() {{
  var search = (document.getElementById('problem-search') || {{}}).value || '';
  search = search.toLowerCase();
  var sourceFilter = (document.getElementById('problem-source-filter') || {{}}).value || '';

  document.querySelectorAll('.problem-card').forEach(function(card) {{
    var source = card.getAttribute('data-source') || '';
    var text = card.textContent.toLowerCase();
    var show = true;
    if (sourceFilter && source !== sourceFilter) show = false;
    if (search && text.indexOf(search) === -1) show = false;
    card.style.display = show ? '' : 'none';
  }});
}}

/* Scorecard filtering */
function filterScorecard() {{
  var search = (document.getElementById('scorecard-search') || {{}}).value || '';
  search = search.toLowerCase();
  var quadrant = (document.getElementById('scorecard-quadrant') || {{}}).value || '';

  var table = document.getElementById('scorecard-table');
  if (!table) return;
  table.querySelectorAll('tbody tr').forEach(function(row) {{
    var rowSearch = (row.getAttribute('data-search') || '').toLowerCase();
    var rowQuadrant = row.getAttribute('data-quadrant') || '';
    var show = true;
    if (search && rowSearch.indexOf(search) === -1) show = false;
    if (quadrant && rowQuadrant !== quadrant) show = false;
    if (row.classList.contains('scorecard-files-row')) {{
      row.style.display = 'none';
    }} else {{
      row.style.display = show ? '' : 'none';
    }}
  }});
}}

/* Scorecard file row toggle */
function toggleScorecardFiles(row) {{
  var next = row.nextElementSibling;
  if (next && next.classList.contains('scorecard-files-row')) {{
    next.style.display = next.style.display === 'none' ? '' : 'none';
  }}
}}

/* Evidence file filtering */
function filterEvidenceFiles(input) {{
  var attempt = input.getAttribute('data-attempt') || '';
  var search = input.value.toLowerCase();
  var list = document.querySelector('.evidence-file-list[data-attempt="' + attempt + '"]');
  if (!list) return;
  list.querySelectorAll('.evidence-file-item').forEach(function(item) {{
    var path = item.getAttribute('data-filepath') || '';
    item.style.display = (!search || path.indexOf(search) !== -1) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate HTML evaluation report from evaluation-results.json"
    )
    parser.add_argument(
        "work_dir",
        help="Path to the workspace directory containing evaluation-results.json",
    )
    parser.add_argument(
        "--output",
        help="Output path for the HTML report (default: <work_dir>/evaluation-report.html)",
    )

    args = parser.parse_args()
    work_dir = Path(args.work_dir)

    if not work_dir.is_dir():
        print(f"Error: Directory not found: {work_dir}", file=sys.stderr)
        sys.exit(1)

    results_path = work_dir / "evaluation-results.json"
    if not results_path.exists():
        print(f"Error: evaluation-results.json not found in {work_dir}", file=sys.stderr)
        sys.exit(1)

    with open(results_path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    # Load comparison data from golden-vs-* subdirectories
    comparison_data: dict[str, dict[str, Any]] = {}
    for subdir in sorted(work_dir.iterdir()):
        if subdir.is_dir() and subdir.name.startswith("golden-vs-"):
            attempt_name = subdir.name.removeprefix("golden-vs-")
            comp_path = subdir / "comparison-data.json"
            if comp_path.exists():
                try:
                    with open(comp_path, "r", encoding="utf-8") as f:
                        comparison_data[attempt_name] = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

    # Load LLM assessment
    llm_assessment: dict[str, Any] | None = None
    llm_path = work_dir / "llm-assessment.json"
    if llm_path.exists():
        try:
            with open(llm_path, "r", encoding="utf-8") as f:
                llm_assessment = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Load scorecard
    scorecard: dict[str, Any] | None = None
    scorecard_path = work_dir / "scorecard.json"
    if scorecard_path.exists():
        try:
            with open(scorecard_path, "r", encoding="utf-8") as f:
                scorecard = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    html_output = generate_html(
        data,
        comparison_data=comparison_data,
        llm_assessment=llm_assessment,
        scorecard=scorecard,
        work_dir=work_dir,
    )

    output_path = Path(args.output) if args.output else work_dir / "evaluation-report.html"
    output_path.write_text(html_output, encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
