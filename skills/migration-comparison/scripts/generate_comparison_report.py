#!/usr/bin/env python3
"""
Generate a self-contained HTML comparison report from comparison-data.json.

Produces a tabbed report with: Summary, File Changes, Semantic Analysis,
Side-by-Side View, and Errors.

Follows the same CSS design system as generate_migration_report.py.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Any


def load_comparison_data(work_dir: str | Path) -> dict[str, Any]:
    json_path = Path(work_dir) / "comparison-data.json"
    if not json_path.exists():
        print(f"Error: comparison-data.json not found in {work_dir}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in comparison-data.json: {e}", file=sys.stderr)
        sys.exit(1)


def escape(text: Any) -> str:
    """HTML-escape a string."""
    return html_mod.escape(str(text)) if text else ""


def status_badge(status: str) -> str:
    colors: dict[str, tuple[str, str]] = {
        "added": ("#16a34a", "#dcfce7"),
        "removed": ("#dc2626", "#fee2e2"),
        "modified": ("#2563eb", "#dbeafe"),
        "identical": ("#6b7280", "#f3f4f6"),
        "gumtree": ("#7c3aed", "#ede9fe"),
        "text": ("#0891b2", "#cffafe"),
        "binary_skip": ("#6b7280", "#f3f4f6"),
        "error": ("#dc2626", "#fee2e2"),
    }
    fg, bg = colors.get(status, ("#6b7280", "#f3f4f6"))
    return f'<span class="badge" style="color:{fg};background:{bg}">{escape(status)}</span>'


def category_badge(cat: str) -> str:
    colors: dict[str, tuple[str, str]] = {
        "structural": ("#b45309", "#fef3c7"),
        "semantic": ("#7c3aed", "#ede9fe"),
        "api_changes": ("#dc2626", "#fee2e2"),
        "cosmetic": ("#6b7280", "#f3f4f6"),
        "additive": ("#16a34a", "#dcfce7"),
        "subtractive": ("#ea580c", "#fff7ed"),
    }
    fg, bg = colors.get(cat, ("#6b7280", "#f3f4f6"))
    label = cat.replace("_", " ").title()
    return f'<span class="badge" style="color:{fg};background:{bg}">{label}</span>'


def render_summary(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {})
    summary = data.get("summary", {})
    categories = data.get("categories", {})

    # Overview cards
    cards: list[tuple[str, int, str, str]] = [
        ("Total Files", summary.get("total_files_compared", 0), "#2563eb", "#dbeafe"),
        ("Modified", summary.get("files_modified", 0), "#7c3aed", "#ede9fe"),
        ("Added", summary.get("files_added", 0), "#16a34a", "#dcfce7"),
        ("Removed", summary.get("files_removed", 0), "#dc2626", "#fee2e2"),
        ("Identical", summary.get("files_identical", 0), "#6b7280", "#f3f4f6"),
    ]

    cards_html = '<div class="status-grid">'
    for label, value, fg, bg in cards:
        cards_html += f'''<div class="status-item">
            <span class="status-label">{label}</span>
            <span style="font-size:24px;font-weight:700;color:{fg}">{value}</span>
        </div>'''
    cards_html += '</div>'

    # Diff method breakdown
    method_html = '<div class="info-row">'
    method_html += f'<span>AST diffs: <strong>{summary.get("ast_diffs_performed", 0)}</strong></span>'
    method_html += f'<span>Text diffs: <strong>{summary.get("text_diffs_performed", 0)}</strong></span>'
    method_html += f'<span>Lines added: <strong style="color:#16a34a">+{summary.get("total_lines_added", 0)}</strong></span>'
    method_html += f'<span>Lines removed: <strong style="color:#dc2626">-{summary.get("total_lines_removed", 0)}</strong></span>'
    method_html += '</div>'

    # GumTree info
    gt_available: bool = metadata.get("gumtree_available", False)
    gt_method: str = metadata.get("gumtree_method", "none")
    if gt_available:
        gt_html = f'<div class="banner banner-info">GumTree AST diffing: enabled ({gt_method})</div>'
    else:
        gt_html = '<div class="banner banner-muted">GumTree AST diffing: not available (text diff only)</div>'

    # Category breakdown
    cat_html = '<h3>Change Categories</h3><table><thead><tr><th>Category</th><th>Files</th><th>Description</th></tr></thead><tbody>'
    cat_descriptions: dict[str, str] = {
        "structural": "Code moved, reordered, or renamed",
        "semantic": "Logic or value changes",
        "api_changes": "Import, export, or module reference changes",
        "cosmetic": "Whitespace or formatting only",
        "additive": "New code added",
        "subtractive": "Code removed",
    }
    for cat_name in ["structural", "semantic", "api_changes", "cosmetic", "additive", "subtractive"]:
        cat_info = categories.get(cat_name, {})
        count: int = cat_info.get("count", 0)
        desc = cat_descriptions.get(cat_name, "")
        cat_html += f'<tr><td>{category_badge(cat_name)}</td><td>{count}</td><td>{escape(desc)}</td></tr>'
    cat_html += '</tbody></table>'

    return f'{cards_html}{method_html}{gt_html}{cat_html}'


def render_file_changes(data: dict[str, Any]) -> str:
    files = data.get("files", {})
    added: list[dict[str, Any]] = files.get("added", [])
    removed: list[dict[str, Any]] = files.get("removed", [])
    modified: list[dict[str, Any]] = files.get("modified", [])

    html_parts: list[str] = []
    html_parts.append('<div class="filter-bar">')
    html_parts.append('<input type="text" id="file-filter" placeholder="Filter files..." onkeyup="filterFiles()">')
    html_parts.append('<select id="status-filter" onchange="filterFiles()">')
    html_parts.append('<option value="">All statuses</option>')
    html_parts.append('<option value="added">Added</option>')
    html_parts.append('<option value="removed">Removed</option>')
    html_parts.append('<option value="modified">Modified</option>')
    html_parts.append('</select>')
    html_parts.append('<select id="category-filter" onchange="filterFiles()">')
    html_parts.append('<option value="">All categories</option>')
    for cat in ["structural", "semantic", "api_changes", "cosmetic", "additive", "subtractive"]:
        html_parts.append(f'<option value="{cat}">{cat.replace("_", " ").title()}</option>')
    html_parts.append('</select>')
    html_parts.append('</div>')

    html_parts.append('<table id="file-table"><thead><tr>')
    html_parts.append('<th>File</th><th>Status</th><th>Categories</th><th>Method</th><th>+/-</th>')
    html_parts.append('</tr></thead><tbody>')

    for f in added:
        path = escape(f.get("path", ""))
        lang = escape(f.get("language", ""))
        html_parts.append(f'<tr data-status="added" data-categories="" data-path="{path}">')
        html_parts.append(f'<td><code>{path}</code> <span class="lang-tag">{lang}</span></td>')
        html_parts.append(f'<td>{status_badge("added")}</td><td></td><td></td><td></td></tr>')

    for f in removed:
        path = escape(f.get("path", ""))
        lang = escape(f.get("language", ""))
        html_parts.append(f'<tr data-status="removed" data-categories="" data-path="{path}">')
        html_parts.append(f'<td><code>{path}</code> <span class="lang-tag">{lang}</span></td>')
        html_parts.append(f'<td>{status_badge("removed")}</td><td></td><td></td><td></td></tr>')

    for f in modified:
        path = escape(f.get("path", ""))
        cats: list[str] = f.get("categories", [])
        cats_html = " ".join(category_badge(c) for c in cats)
        cats_data = " ".join(cats)
        method: str = f.get("diff_method", "text")
        stats: dict[str, Any] = f.get("stats", {})
        la: int = stats.get("lines_added", 0)
        lr: int = stats.get("lines_removed", 0)
        diff_stat = f'<span style="color:#16a34a">+{la}</span> <span style="color:#dc2626">-{lr}</span>'

        html_parts.append(f'<tr data-status="modified" data-categories="{cats_data}" data-path="{path}">')
        html_parts.append(f'<td><code>{path}</code></td>')
        html_parts.append(f'<td>{status_badge("modified")}</td>')
        html_parts.append(f'<td>{cats_html}</td>')
        html_parts.append(f'<td>{status_badge(method)}</td>')
        html_parts.append(f'<td>{diff_stat}</td></tr>')

    html_parts.append('</tbody></table>')
    return "\n".join(html_parts)


def render_semantic_analysis(data: dict[str, Any]) -> str:
    categories = data.get("categories", {})
    annotations: list[dict[str, str]] = data.get("annotations", [])

    html_parts: list[str] = []

    # Build annotation index by path
    annot_by_path: dict[str, list[dict[str, str]]] = {}
    for annot in annotations:
        p = annot.get("path", "")
        annot_by_path.setdefault(p, []).append(annot)

    cat_descriptions: dict[str, str] = {
        "structural": "Code that was moved, reordered, or renamed without changing behavior.",
        "semantic": "Changes to logic, values, or behavior of existing code.",
        "api_changes": "Changes to imports, exports, or module references indicating API surface changes.",
        "cosmetic": "Whitespace, formatting, or style-only changes with no functional impact.",
        "additive": "New code that was added without modifying existing code.",
        "subtractive": "Code that was removed without replacement.",
    }

    for cat_name in ["api_changes", "semantic", "structural", "additive", "subtractive", "cosmetic"]:
        cat_info = categories.get(cat_name, {})
        cat_files: list[str] = cat_info.get("files", [])
        if not cat_files:
            continue

        desc = cat_descriptions.get(cat_name, "")
        html_parts.append('<div class="category-section">')
        html_parts.append(f'<h3>{category_badge(cat_name)} <span class="cat-count">({len(cat_files)} files)</span></h3>')
        html_parts.append(f'<p class="cat-desc">{escape(desc)}</p>')
        html_parts.append('<ul class="file-list">')

        for fpath in cat_files:
            file_annots = annot_by_path.get(fpath, [])
            annot_html = ""
            if file_annots:
                annot_html = '<ul class="annotations">'
                for a in file_annots:
                    annot_html += f'<li>{escape(a.get("text", ""))}</li>'
                annot_html += '</ul>'
            html_parts.append(f'<li><code>{escape(fpath)}</code>{annot_html}</li>')

        html_parts.append('</ul></div>')

    if not html_parts:
        html_parts.append('<p class="muted">No categorized changes found.</p>')

    return "\n".join(html_parts)


def render_side_by_side(data: dict[str, Any]) -> str:
    modified: list[dict[str, Any]] = data.get("files", {}).get("modified", [])
    if not modified:
        return '<p class="muted">No modified files to display.</p>'

    html_parts: list[str] = []
    html_parts.append('<div class="diff-controls">')
    html_parts.append('<select id="diff-file-select" onchange="showDiff(this.value)">')
    html_parts.append('<option value="">Select a file...</option>')
    for i, f in enumerate(modified):
        path = escape(f.get("path", ""))
        stats: dict[str, Any] = f.get("stats", {})
        la: int = stats.get("lines_added", 0)
        lr: int = stats.get("lines_removed", 0)
        html_parts.append(f'<option value="diff-{i}">{path} (+{la}/-{lr})</option>')
    html_parts.append('</select></div>')

    for i, f in enumerate(modified):
        path = f.get("path", "")
        diff_text: str = f.get("text_diff", "")
        if not diff_text:
            continue

        left_lines, right_lines = parse_unified_diff(diff_text)

        max_display = 200
        truncated = False
        if len(left_lines) > max_display:
            left_lines = left_lines[:max_display]
            right_lines = right_lines[:max_display]
            truncated = True

        html_parts.append(f'<div class="diff-pane" id="diff-{i}" style="display:none">')
        html_parts.append(f'<h4>{escape(path)}</h4>')
        html_parts.append('<div class="diff-container"><table class="diff-table"><tbody>')

        for j in range(len(left_lines)):
            ll = left_lines[j] if j < len(left_lines) else ("", "", "")
            rl = right_lines[j] if j < len(right_lines) else ("", "", "")

            l_num, l_class, l_text = ll
            r_num, r_class, r_text = rl

            html_parts.append('<tr>')
            html_parts.append(f'<td class="line-num">{l_num}</td>')
            html_parts.append(f'<td class="diff-line {l_class}">{escape(l_text)}</td>')
            html_parts.append(f'<td class="line-num">{r_num}</td>')
            html_parts.append(f'<td class="diff-line {r_class}">{escape(r_text)}</td>')
            html_parts.append('</tr>')

        html_parts.append('</tbody></table></div>')
        if truncated:
            html_parts.append(f'<p class="muted">Diff truncated (showing first {max_display} lines)</p>')
        html_parts.append('</div>')

    return "\n".join(html_parts)


def parse_unified_diff(diff_text: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Parse unified diff text into paired left/right lines for side-by-side display."""
    left_lines: list[tuple[str, str, str]] = []
    right_lines: list[tuple[str, str, str]] = []
    left_num = 0
    right_num = 0

    lines = diff_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("---") or line.startswith("+++"):
            i += 1
            continue

        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)", line)
            if match:
                left_num = int(match.group(1)) - 1
            match2 = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            if match2:
                right_num = int(match2.group(1)) - 1

            left_lines.append(("", "hunk-header", line))
            right_lines.append(("", "hunk-header", line))
            i += 1
            continue

        if line.startswith("-"):
            left_num += 1
            left_lines.append((str(left_num), "diff-removed", line[1:]))
            right_lines.append(("", "diff-empty", ""))
        elif line.startswith("+"):
            right_num += 1
            left_lines.append(("", "diff-empty", ""))
            right_lines.append((str(right_num), "diff-added", line[1:]))
        elif line.startswith(" ") or line == "":
            left_num += 1
            right_num += 1
            content = line[1:] if line.startswith(" ") else ""
            left_lines.append((str(left_num), "", content))
            right_lines.append((str(right_num), "", content))

        i += 1

    return left_lines, right_lines


def load_scoring_results(work_dir: str | Path) -> dict[str, Any] | None:
    """Load scoring-results.json from the workspace directory. Returns None if absent."""
    json_path = Path(work_dir) / "scoring-results.json"
    if not json_path.exists():
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data
    except (json.JSONDecodeError, OSError):
        return None


def score_badge(grade: str, percent: int) -> str:
    """Render a color-coded grade badge."""
    grade_colors: dict[str, tuple[str, str]] = {
        "A": ("#16a34a", "#dcfce7"),
        "B": ("#2563eb", "#dbeafe"),
        "C": ("#ca8a04", "#fef9c3"),
        "D": ("#ea580c", "#fff7ed"),
        "F": ("#dc2626", "#fee2e2"),
    }
    fg, bg = grade_colors.get(grade, ("#6b7280", "#f3f4f6"))
    return (
        f'<span style="display:inline-block;padding:8px 20px;border-radius:12px;'
        f'font-size:28px;font-weight:800;color:{fg};background:{bg}">'
        f'{grade} ({percent}%)</span>'
    )


def render_scoring_tab(scoring: dict[str, Any]) -> str:
    """Render the Quality Score tab HTML."""
    score_data = scoring.get("score", {})
    grade = score_data.get("grade", "?")
    percent = score_data.get("overall_percent", 0)
    components = score_data.get("components", {})
    pattern_results: list[dict[str, Any]] = scoring.get("pattern_results", [])
    noise_instances: list[dict[str, Any]] = scoring.get("noise_instances", [])
    recommendations: list[dict[str, Any]] = scoring.get("recommendations", [])
    metadata = scoring.get("metadata", {})

    html_parts: list[str] = []

    # Grade badge
    html_parts.append('<div style="text-align:center;margin-bottom:24px">')
    html_parts.append(f'<h2 style="margin-bottom:12px">Migration Quality Score</h2>')
    html_parts.append(score_badge(grade, percent))
    target = metadata.get("target")
    if target:
        html_parts.append(f'<p style="margin-top:8px;color:#6b7280">Target: {escape(target)} '
                          f'({metadata.get("target_patterns_loaded", 0)} patterns)</p>')
    html_parts.append('</div>')

    # Component cards
    fc = components.get("file_coverage", {})
    ps = components.get("pattern_score", {})
    np_ = components.get("noise_penalty", {})

    html_parts.append('<div class="status-grid">')
    html_parts.append(f'''<div class="status-item">
        <span class="status-label">File Coverage</span>
        <span style="font-size:24px;font-weight:700;color:#2563eb">{fc.get("score", 0):.0%}</span>
        <span style="font-size:12px;color:#6b7280">{fc.get("matched", 0)}/{fc.get("total", 0)} files (weight {fc.get("weight", 0.2):.0%})</span>
    </div>''')
    html_parts.append(f'''<div class="status-item">
        <span class="status-label">Pattern Score</span>
        <span style="font-size:24px;font-weight:700;color:#7c3aed">{ps.get("score", 0):.0%}</span>
        <span style="font-size:12px;color:#6b7280">weight {ps.get("weight", 0.65):.0%}</span>
    </div>''')

    np_color = "#16a34a" if np_.get("raw_penalty", 0) < 0.1 else ("#ea580c" if np_.get("raw_penalty", 0) < 0.3 else "#dc2626")
    html_parts.append(f'''<div class="status-item">
        <span class="status-label">Noise Penalty</span>
        <span style="font-size:24px;font-weight:700;color:{np_color}">{np_.get("raw_penalty", 0):.0%}</span>
        <span style="font-size:12px;color:#6b7280">{np_.get("instance_count", 0)} instances (weight {np_.get("weight", 0.15):.0%})</span>
    </div>''')
    html_parts.append('</div>')

    # Pattern results table (if target-specific)
    applicable_count = sum(1 for p in pattern_results if p.get("status") != "not_applicable")
    na_count = len(pattern_results) - applicable_count
    if pattern_results:
        html_parts.append(f'<h3>Pattern Results <span style="font-weight:400;font-size:14px;color:#6b7280">'
                          f'({applicable_count} applicable, {na_count} not applicable)</span></h3>')

        # Filter bar
        html_parts.append('<div class="filter-bar">')
        html_parts.append('<input type="text" id="pattern-filter" placeholder="Filter patterns..." onkeyup="filterPatterns()">')
        html_parts.append('<select id="pattern-status-filter" onchange="filterPatterns()">')
        html_parts.append('<option value="">All statuses</option>')
        html_parts.append('<option value="correct">Correct</option>')
        html_parts.append('<option value="incorrect">Incorrect</option>')
        html_parts.append('<option value="missing">Missing</option>')
        html_parts.append('<option value="file_missing">File Missing</option>')
        html_parts.append('<option value="not_applicable">Not Applicable</option>')
        html_parts.append('</select>')
        html_parts.append('<select id="pattern-complexity-filter" onchange="filterPatterns()">')
        html_parts.append('<option value="">All complexities</option>')
        html_parts.append('<option value="trivial">Trivial</option>')
        html_parts.append('<option value="moderate">Moderate</option>')
        html_parts.append('<option value="complex">Complex</option>')
        html_parts.append('</select>')
        html_parts.append('</div>')

        html_parts.append('<table id="pattern-table"><thead><tr>'
                          '<th>Pattern</th><th>Complexity</th><th>Status</th><th>Files &amp; Details</th>'
                          '</tr></thead><tbody>')

        complexity_badges: dict[str, tuple[str, str]] = {
            "trivial": ("#6b7280", "#f3f4f6"),
            "moderate": ("#b45309", "#fef3c7"),
            "complex": ("#dc2626", "#fee2e2"),
        }
        status_icons: dict[str, str] = {
            "correct": "&#10003;",
            "incorrect": "&#10007;",
            "missing": "&#9888;",
            "file_missing": "&#10005;",
            "not_applicable": "&#8212;",
        }
        status_colors: dict[str, tuple[str, str]] = {
            "correct": ("#16a34a", "#dcfce7"),
            "incorrect": ("#dc2626", "#fee2e2"),
            "missing": ("#ea580c", "#fff7ed"),
            "file_missing": ("#9333ea", "#f3e8ff"),
            "not_applicable": ("#6b7280", "#f3f4f6"),
        }

        for pr in pattern_results:
            name = escape(pr.get("name", pr.get("pattern_id", "")))
            pid = escape(pr.get("pattern_id", ""))
            complexity = pr.get("complexity", "moderate")
            status = pr.get("status", "not_applicable")
            details: list[dict[str, Any]] = pr.get("details", [])

            c_fg, c_bg = complexity_badges.get(complexity, ("#6b7280", "#f3f4f6"))
            s_fg, s_bg = status_colors.get(status, ("#6b7280", "#f3f4f6"))
            icon = status_icons.get(status, "")

            # Build details sub-rows showing per-file information with links
            details_html = escape(pr.get("message", ""))
            if details:
                file_lines: list[str] = []
                for d in details:
                    d_file = escape(d.get("file", ""))
                    d_abs = d.get("abs_path", "")
                    d_line = d.get("line")
                    d_status = d.get("status", "")
                    d_msg = escape(d.get("message", ""))
                    d_s_fg, d_s_bg = status_colors.get(d_status, ("#6b7280", "#f3f4f6"))
                    d_icon = status_icons.get(d_status, "")

                    # Build file reference with optional line number
                    # Use vscode:// URIs so clicking opens the file in the editor
                    if d_abs and d_line:
                        file_ref = (f'<a href="vscode://file{escape(d_abs)}:{d_line}" style="color:#2563eb;text-decoration:none"'
                                    f' title="{escape(d_abs)}:{d_line}">'
                                    f'<code>{d_file}:{d_line}</code></a>')
                    elif d_abs:
                        file_ref = (f'<a href="vscode://file{escape(d_abs)}" style="color:#2563eb;text-decoration:none"'
                                    f' title="{escape(d_abs)}">'
                                    f'<code>{d_file}</code></a>')
                    else:
                        file_ref = f'<code style="color:#2563eb">{d_file}</code>'

                    file_lines.append(
                        f'<div style="margin-top:4px;padding:4px 8px;background:#f9fafb;border-radius:4px;font-size:13px">'
                        f'{file_ref} '
                        f'<span class="badge" style="color:{d_s_fg};background:{d_s_bg};font-size:11px">{d_icon} {d_status}</span> '
                        f'<span style="color:#6b7280">{d_msg}</span>'
                        f'</div>'
                    )
                details_html = "".join(file_lines)

            html_parts.append(f'<tr data-status="{status}" data-complexity="{complexity}" '
                              f'data-name="{name.lower()} {pid}">')
            html_parts.append(f'<td><strong>{name}</strong>'
                              f'<div style="font-size:12px;color:#6b7280;margin-top:2px">{pid}</div></td>')
            html_parts.append(f'<td><span class="badge" style="color:{c_fg};background:{c_bg}">{complexity}</span></td>')
            html_parts.append(f'<td><span class="badge" style="color:{s_fg};background:{s_bg}">{icon} {status}</span></td>')
            html_parts.append(f'<td>{details_html}</td>')
            html_parts.append('</tr>')

        html_parts.append('</tbody></table>')

    # Noise instances table
    if noise_instances:
        html_parts.append('<h3>Noise Instances</h3>')
        html_parts.append('<table><thead><tr><th>Type</th><th>File</th><th>Detail</th><th>Penalty</th></tr></thead><tbody>')

        noise_type_colors: dict[str, tuple[str, str]] = {
            "artifact": ("#dc2626", "#fee2e2"),
            "placeholder_token": ("#ea580c", "#fff7ed"),
            "formatting_only": ("#6b7280", "#f3f4f6"),
            "unnecessary_change": ("#b45309", "#fef3c7"),
            "incorrect_migration": ("#dc2626", "#fee2e2"),
        }

        for ni in noise_instances:
            n_type = ni.get("type", "")
            n_file = escape(ni.get("file", ""))
            n_detail = escape(ni.get("detail", ""))
            n_penalty = ni.get("penalty", 0)
            t_fg, t_bg = noise_type_colors.get(n_type, ("#6b7280", "#f3f4f6"))

            html_parts.append('<tr>')
            html_parts.append(f'<td><span class="badge" style="color:{t_fg};background:{t_bg}">{n_type.replace("_", " ")}</span></td>')
            html_parts.append(f'<td><code>{n_file}</code></td>')
            html_parts.append(f'<td>{n_detail}</td>')
            html_parts.append(f'<td>{n_penalty:.2f}</td>')
            html_parts.append('</tr>')

        html_parts.append('</tbody></table>')

    # Recommendations
    if recommendations:
        html_parts.append('<h3>Recommendations</h3>')
        html_parts.append('<ul style="list-style:none;padding:0">')

        priority_icons: dict[str, tuple[str, str]] = {
            "high": ("#dc2626", "&#9650;"),
            "medium": ("#ea580c", "&#9679;"),
            "low": ("#6b7280", "&#9661;"),
        }

        for rec in recommendations:
            priority = rec.get("priority", "low")
            p_color, p_icon = priority_icons.get(priority, ("#6b7280", "&#9661;"))
            html_parts.append(
                f'<li style="padding:8px 0;border-bottom:1px solid #f1f5f9">'
                f'<span style="color:{p_color};font-weight:600">{p_icon} {priority.upper()}</span> '
                f'{escape(rec.get("message", ""))}</li>'
            )

        html_parts.append('</ul>')

    return "\n".join(html_parts)


def render_errors(data: dict[str, Any]) -> str:
    errors: list[dict[str, str]] = data.get("errors", [])
    if not errors:
        return ""

    html_parts: list[str] = ['<table><thead><tr><th>File</th><th>Error</th></tr></thead><tbody>']
    for err in errors:
        path = escape(err.get("path", ""))
        error = escape(err.get("error", ""))
        html_parts.append(f'<tr><td><code>{path}</code></td><td>{error}</td></tr>')
    html_parts.append('</tbody></table>')
    return "\n".join(html_parts)


def generate_html(data: dict[str, Any], scoring: dict[str, Any] | None = None) -> str:
    metadata = data.get("metadata", {})
    summary = data.get("summary", {})
    errors: list[dict[str, str]] = data.get("errors", [])

    repo_a: dict[str, str] = metadata.get("repo_a", {})
    repo_b: dict[str, str] = metadata.get("repo_b", {})
    label_a: str = repo_a.get("label", "Reference A")
    label_b: str = repo_b.get("label", "Reference B")
    timestamp: str = metadata.get("timestamp", datetime.now().isoformat())

    try:
        ts_display = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts_display = timestamp

    summary_html = render_summary(data)
    file_changes_html = render_file_changes(data)
    semantic_html = render_semantic_analysis(data)
    side_by_side_html = render_side_by_side(data)
    errors_html = render_errors(data)

    has_errors = len(errors) > 0
    errors_tab = '<button class="tab" onclick="switchTab(\'errors\')">Errors</button>' if has_errors else ""
    errors_section = f'<div id="errors" class="tab-content" data-title="Errors">{errors_html}</div>' if has_errors else ""

    # Scoring tab
    scoring_tab = ""
    scoring_section = ""
    score_banner = ""
    if scoring is not None:
        scoring_tab = '<button class="tab" onclick="switchTab(\'quality-score\')">Quality Score</button>'
        scoring_html = render_scoring_tab(scoring)
        scoring_section = f'<div id="quality-score" class="tab-content" data-title="Quality Score">{scoring_html}</div>'
        score_data = scoring.get("score", {})
        s_grade = score_data.get("grade", "?")
        s_percent = score_data.get("overall_percent", 0)
        score_banner = f' &mdash; Quality: {score_badge(s_grade, s_percent)}'

    total_modified: int = summary.get("files_modified", 0)
    total_added: int = summary.get("files_added", 0)
    total_removed: int = summary.get("files_removed", 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Migration Comparison - {escape(label_a)} vs {escape(label_b)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1f2937; background: #f9fafb; line-height: 1.5; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
  header {{ background: #1e293b; color: white; padding: 32px; margin: -24px -24px 24px; }}
  header h1 {{ font-size: 24px; margin-bottom: 8px; }}
  .header-meta {{ display: flex; gap: 24px; flex-wrap: wrap; font-size: 14px; color: #94a3b8; }}
  .header-meta span {{ display: flex; align-items: center; gap: 4px; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
  .tabs {{ display: flex; gap: 0; border-bottom: 2px solid #e5e7eb; margin-bottom: 24px; }}
  .tab {{ background: none; border: none; padding: 12px 24px; cursor: pointer; font-size: 14px; font-weight: 500; color: #6b7280; border-bottom: 2px solid transparent; margin-bottom: -2px; }}
  .tab:hover {{ color: #1f2937; }}
  .tab.active {{ color: #2563eb; border-bottom-color: #2563eb; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .banner {{ padding: 16px 20px; border-radius: 8px; margin-bottom: 16px; font-weight: 500; }}
  .banner-info {{ background: #dbeafe; color: #2563eb; }}
  .banner-muted {{ background: #f3f4f6; color: #6b7280; }}
  .status-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .status-item {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; flex-direction: column; gap: 8px; }}
  .status-label {{ font-size: 13px; color: #6b7280; font-weight: 500; }}
  .info-row {{ display: flex; gap: 24px; flex-wrap: wrap; padding: 12px 0; margin-bottom: 16px; font-size: 14px; color: #4b5563; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{ background: #f8fafc; text-align: left; padding: 10px 16px; font-size: 13px; font-weight: 600; color: #475569; border-bottom: 1px solid #e5e7eb; }}
  td {{ padding: 10px 16px; font-size: 14px; border-bottom: 1px solid #f1f5f9; }}
  code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-size: 13px; }}
  h3 {{ font-size: 18px; margin-bottom: 12px; color: #1e293b; }}
  h4 {{ font-size: 15px; margin-bottom: 8px; color: #334155; }}
  .muted {{ color: #9ca3af; font-style: italic; }}
  .lang-tag {{ font-size: 11px; color: #9ca3af; margin-left: 4px; }}
  .filter-bar {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .filter-bar input, .filter-bar select {{ padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; }}
  .filter-bar input {{ flex: 1; min-width: 200px; }}
  .category-section {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .cat-count {{ font-size: 14px; color: #6b7280; font-weight: 400; }}
  .cat-desc {{ font-size: 14px; color: #6b7280; margin-bottom: 12px; }}
  .file-list {{ margin: 0 0 0 20px; }}
  .file-list li {{ margin-bottom: 6px; font-size: 14px; }}
  .annotations {{ margin: 4px 0 0 16px; list-style: disc; }}
  .annotations li {{ color: #4b5563; font-size: 13px; }}
  .diff-controls {{ margin-bottom: 16px; }}
  .diff-controls select {{ padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; min-width: 400px; }}
  .diff-pane {{ margin-bottom: 24px; }}
  .diff-container {{ overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 8px; }}
  .diff-table {{ width: 100%; border-collapse: collapse; font-family: "SF Mono", "Fira Code", monospace; font-size: 13px; margin: 0; box-shadow: none; }}
  .diff-table td {{ padding: 0 8px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; border-bottom: none; }}
  .line-num {{ width: 50px; color: #9ca3af; text-align: right; user-select: none; background: #f8fafc; border-right: 1px solid #e5e7eb; }}
  .diff-removed {{ background: #fee2e2; }}
  .diff-added {{ background: #dcfce7; }}
  .diff-empty {{ background: #f9fafb; }}
  .hunk-header {{ background: #dbeafe; color: #2563eb; font-weight: 500; }}
  @media print {{
    body {{ background: white; }}
    .container {{ max-width: none; padding: 0; }}
    header {{ background: #1e293b !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .tab-content {{ display: block !important; page-break-inside: avoid; }}
    .tabs {{ display: none; }}
    .tab-content::before {{ content: attr(data-title); display: block; font-size: 20px; font-weight: 700; margin: 24px 0 12px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Migration Comparison</h1>
    <div class="header-meta">
      <span>{escape(label_a)} vs {escape(label_b)}</span>
      <span>{status_badge("modified")} {total_modified} modified</span>
      <span style="color:#16a34a">+{total_added} added</span>
      <span style="color:#dc2626">-{total_removed} removed</span>
      <span>{ts_display}</span>
    </div>
  </header>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('summary')">Summary</button>
    {scoring_tab}
    <button class="tab" onclick="switchTab('file-changes')">File Changes</button>
    <button class="tab" onclick="switchTab('semantic')">Semantic Analysis</button>
    <button class="tab" onclick="switchTab('side-by-side')">Side-by-Side View</button>
    {errors_tab}
  </div>

  <div id="summary" class="tab-content active" data-title="Summary">
    {score_banner}
    {summary_html}
  </div>

  {scoring_section}

  <div id="file-changes" class="tab-content" data-title="File Changes">
    {file_changes_html}
  </div>

  <div id="semantic" class="tab-content" data-title="Semantic Analysis">
    {semantic_html}
  </div>

  <div id="side-by-side" class="tab-content" data-title="Side-by-Side View">
    {side_by_side_html}
  </div>

  {errors_section}

</div>
<script>
function switchTab(id) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
}}

function filterFiles() {{
  var text = document.getElementById('file-filter').value.toLowerCase();
  var status = document.getElementById('status-filter').value;
  var category = document.getElementById('category-filter').value;
  var rows = document.querySelectorAll('#file-table tbody tr');
  rows.forEach(function(row) {{
    var path = (row.getAttribute('data-path') || '').toLowerCase();
    var rowStatus = row.getAttribute('data-status') || '';
    var rowCats = row.getAttribute('data-categories') || '';
    var show = true;
    if (text && path.indexOf(text) === -1) show = false;
    if (status && rowStatus !== status) show = false;
    if (category && rowCats.indexOf(category) === -1) show = false;
    row.style.display = show ? '' : 'none';
  }});
}}

function filterPatterns() {{
  var text = (document.getElementById('pattern-filter') || {{}}).value || '';
  text = text.toLowerCase();
  var status = (document.getElementById('pattern-status-filter') || {{}}).value || '';
  var complexity = (document.getElementById('pattern-complexity-filter') || {{}}).value || '';
  var rows = document.querySelectorAll('#pattern-table tbody tr');
  rows.forEach(function(row) {{
    var name = (row.getAttribute('data-name') || '').toLowerCase();
    var rowStatus = row.getAttribute('data-status') || '';
    var rowComplexity = row.getAttribute('data-complexity') || '';
    var show = true;
    if (text && name.indexOf(text) === -1) show = false;
    if (status && rowStatus !== status) show = false;
    if (complexity && rowComplexity !== complexity) show = false;
    row.style.display = show ? '' : 'none';
  }});
}}

function showDiff(id) {{
  document.querySelectorAll('.diff-pane').forEach(el => el.style.display = 'none');
  if (id) document.getElementById(id).style.display = 'block';
}}
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a self-contained HTML comparison report from comparison-data.json"
    )
    parser.add_argument(
        "work_dir",
        help="Path to the workspace directory containing comparison-data.json",
    )
    parser.add_argument(
        "--output",
        help="Output path for the HTML report (default: <work_dir>/comparison-report.html)",
    )

    args = parser.parse_args()
    work_dir = Path(args.work_dir)

    if not work_dir.is_dir():
        print(f"Error: Directory not found: {work_dir}", file=sys.stderr)
        sys.exit(1)

    data = load_comparison_data(work_dir)
    scoring = load_scoring_results(work_dir)
    html_output = generate_html(data, scoring=scoring)

    output_path = Path(args.output) if args.output else work_dir / "comparison-report.html"
    output_path.write_text(html_output, encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
