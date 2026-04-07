#!/usr/bin/env python3
"""
PatternFly 5→6 migration pattern detectors.

Each detector inspects reference and candidate diffs/content/AST to determine
whether a specific PF5→PF6 migration pattern was correctly applied, incorrectly
applied, or missing.

Uses tree-sitter for AST analysis of TSX/TS files and regex on diff text
for simpler patterns.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# Ensure scripts dir is importable
_SCRIPTS_DIR = str(Path(__file__).parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from ast_helpers import find_imports, jsx_find_components, jsx_find_prop_on_component, jsx_get_children
except ImportError:
    # Stubs if ast_helpers not available
    def find_imports(tree: Any, source: str) -> list[dict[str, Any]]:  # type: ignore[misc]
        return []

    def jsx_find_components(tree: Any, source: str) -> list[dict[str, Any]]:  # type: ignore[misc]
        return []

    def jsx_find_prop_on_component(tree: Any, source: str, comp: str, prop: str) -> bool:  # type: ignore[misc]
        return False

    def jsx_get_children(tree: Any, source: str, comp: str) -> list[str]:  # type: ignore[misc]
        return []


# ---------------------------------------------------------------------------
# Helper for standard detector result
# ---------------------------------------------------------------------------

def _result(
    pattern_id: str,
    status: str,
    message: str = "",
    details: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "pattern_id": pattern_id,
        "status": status,
        "message": message,
        "details": details or [],
    }


def _not_applicable(pattern_id: str) -> dict[str, Any]:
    return _result(pattern_id, "not_applicable", "Not applicable to this file")


def _diff_has_pattern(diff: str | None, pattern: str) -> bool:
    """Check if a regex pattern appears in added lines of a diff."""
    if not diff:
        return False
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            if re.search(pattern, line[1:]):
                return True
    return False


def _diff_removes_pattern(diff: str | None, pattern: str) -> bool:
    """Check if a regex pattern appears in removed lines of a diff."""
    if not diff:
        return False
    for line in diff.split("\n"):
        if line.startswith("-") and not line.startswith("---"):
            if re.search(pattern, line[1:]):
                return True
    return False


def _content_has_import(content: str | None, module_pattern: str) -> bool:
    """Check if content imports from a module matching a pattern."""
    if not content:
        return False
    return bool(re.search(rf"""from\s+['"]({module_pattern})['"]""", content))


# ---------------------------------------------------------------------------
# Trivial patterns (weight 1)
# ---------------------------------------------------------------------------

def detect_css_class_prefix(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect pf-v5- → pf-v6- CSS class prefix migration."""
    pid = "css-class-prefix"
    if not ref_diff or not _diff_has_pattern(ref_diff, r"pf-v[56]-"):
        return _not_applicable(pid)

    ref_has_v6 = _diff_has_pattern(ref_diff, r"pf-v6-")
    cand_has_v6 = _diff_has_pattern(cand_diff, r"pf-v6-")
    cand_still_v5 = cand_content and re.search(r"pf-v5-", cand_content)

    if cand_has_v6 and not cand_still_v5:
        return _result(pid, "correct", "CSS class prefixes updated from pf-v5- to pf-v6-")
    if cand_has_v6 and cand_still_v5:
        return _result(pid, "incorrect", "Partial CSS class prefix migration — some pf-v5- remain")
    if not cand_has_v6 and ref_has_v6:
        return _result(pid, "missing", "CSS class prefix migration not applied")
    return _not_applicable(pid)


def detect_utility_class_rename(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect PF utility class renames (e.g., pf-u-* → pf-v6-u-*)."""
    pid = "utility-class-rename"
    if not ref_diff or not _diff_has_pattern(ref_diff, r"pf-u-|pf-v6-u-"):
        return _not_applicable(pid)

    ref_renames = _diff_has_pattern(ref_diff, r"pf-v6-u-")
    cand_renames = _diff_has_pattern(cand_diff, r"pf-v6-u-")
    cand_old = cand_content and re.search(r"\bpf-u-\w", cand_content)

    if cand_renames and not cand_old:
        return _result(pid, "correct", "Utility classes renamed to pf-v6-u-*")
    if cand_renames and cand_old:
        return _result(pid, "incorrect", "Partial utility class rename — some pf-u-* remain")
    if ref_renames and not cand_renames:
        return _result(pid, "missing", "Utility class renames not applied")
    return _not_applicable(pid)


def detect_css_logical_properties(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect CSS logical property migration via PF design token names.

    PF5→PF6 renames token variables like PaddingTop → PaddingBlockStart,
    MarginLeft → MarginInlineStart, etc. (PascalCase token names).
    Also checks for CSS property-level equivalents.
    """
    pid = "css-logical-properties"
    # PF token-style names (PascalCase, as used in design token imports)
    logical_tokens = r"(Padding|Margin)(Block|Inline)(Start|End)"
    # Also check CSS property syntax as fallback
    logical_css = r"(margin|padding)-(inline|block)-(start|end)"

    ref_has_logical = (
        _diff_has_pattern(ref_diff, logical_tokens) or
        _diff_has_pattern(ref_diff, logical_css)
    )
    if not ref_diff or not ref_has_logical:
        return _not_applicable(pid)

    cand_has_logical = (
        _diff_has_pattern(cand_diff, logical_tokens) or
        _diff_has_pattern(cand_diff, logical_css)
    )

    if cand_has_logical:
        return _result(pid, "correct", "CSS logical properties adopted")
    return _result(pid, "missing", "CSS logical property migration not applied")


def detect_theme_dark_removal(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect removal of theme='dark' prop and ThemeVariant.dark.

    PF6 removes the theme prop; dark mode is handled differently.
    Also catches .pf-theme-dark CSS class changes.
    """
    pid = "theme-dark-removal"
    if not ref_diff:
        return _not_applicable(pid)

    # Check for theme="dark" prop or ThemeVariant.dark or .pf-theme-dark
    theme_prop = r"""theme\s*=\s*(?:["']dark["']|\{['"]dark['"]\}|\{ThemeVariant\.dark\})"""
    theme_variant = r"\bThemeVariant\.dark\b"
    theme_css = r"pf-theme-dark"

    ref_removes = (
        _diff_removes_pattern(ref_diff, theme_prop) or
        _diff_removes_pattern(ref_diff, theme_variant) or
        _diff_removes_pattern(ref_diff, theme_css)
    )
    if not ref_removes:
        return _not_applicable(pid)

    cand_removes = (
        _diff_removes_pattern(cand_diff, theme_prop) or
        _diff_removes_pattern(cand_diff, theme_variant) or
        _diff_removes_pattern(cand_diff, theme_css)
    )
    cand_still_has = cand_content and (
        re.search(theme_prop, cand_content) or
        re.search(theme_variant, cand_content) or
        re.search(r"\.pf-theme-dark\b", cand_content)
    )

    if cand_removes and not cand_still_has:
        return _result(pid, "correct", "theme dark usage removed")
    if cand_still_has:
        return _result(pid, "missing", "theme='dark' or ThemeVariant.dark still present")
    return _not_applicable(pid)


def detect_inner_ref_to_ref(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect innerRef → ref prop migration."""
    pid = "inner-ref-to-ref"
    if not ref_diff or not _diff_removes_pattern(ref_diff, r"\binnerRef\b"):
        return _not_applicable(pid)

    cand_removes_inner = _diff_removes_pattern(cand_diff, r"\binnerRef\b")
    cand_adds_ref = _diff_has_pattern(cand_diff, r'\bref[=\s{]')
    cand_still_has = cand_content and re.search(r"\binnerRef\b", cand_content)

    if cand_removes_inner and not cand_still_has:
        return _result(pid, "correct", "innerRef migrated to ref")
    if cand_still_has:
        return _result(pid, "missing", "innerRef still used instead of ref")
    return _not_applicable(pid)


def detect_align_right_to_end(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect alignRight → alignEnd prop rename.

    PF6 renames the boolean prop `alignRight` to `alignEnd` (and
    `alignLeft` to `alignStart` where applicable).
    """
    pid = "align-right-to-end"
    if not ref_diff:
        return _not_applicable(pid)

    ref_has_change = (
        _diff_removes_pattern(ref_diff, r"\balignRight\b") or
        _diff_has_pattern(ref_diff, r"\balignEnd\b")
    )
    if not ref_has_change:
        return _not_applicable(pid)

    cand_has_new = (
        _diff_has_pattern(cand_diff, r"\balignEnd\b") or
        _diff_has_pattern(cand_diff, r"\balignStart\b")
    )
    cand_removes_old = _diff_removes_pattern(cand_diff, r"\balignRight\b")
    cand_still_old = cand_content and re.search(r"\balignRight\b", cand_content)

    if (cand_has_new or cand_removes_old) and not cand_still_old:
        return _result(pid, "correct", "alignRight renamed to alignEnd")
    if cand_still_old:
        return _result(pid, "missing", "alignRight still used instead of alignEnd")
    return _not_applicable(pid)


def detect_is_action_cell(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Td isActionCell → hasAction prop rename."""
    pid = "is-action-cell"
    if not ref_diff or not _diff_removes_pattern(ref_diff, r"\bisActionCell\b"):
        return _not_applicable(pid)

    cand_removes = _diff_removes_pattern(cand_diff, r"\bisActionCell\b")
    cand_adds_new = _diff_has_pattern(cand_diff, r"\bhasAction\b")
    cand_still_has = cand_content and re.search(r"\bisActionCell\b", cand_content)

    if cand_removes and cand_adds_new and not cand_still_has:
        return _result(pid, "correct", "isActionCell renamed to hasAction")
    if cand_removes and not cand_adds_new and not cand_still_has:
        return _result(pid, "incorrect", "isActionCell removed but hasAction not added")
    if cand_still_has:
        return _result(pid, "missing", "isActionCell prop still present")
    return _not_applicable(pid)


def detect_space_items_removal(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect spaceItems prop removal from Flex/FlexItem."""
    pid = "space-items-removal"
    if not ref_diff or not _diff_removes_pattern(ref_diff, r"\bspaceItems\b"):
        return _not_applicable(pid)

    cand_removes = _diff_removes_pattern(cand_diff, r"\bspaceItems\b")
    cand_still_has = cand_content and re.search(r"\bspaceItems\b", cand_content)

    if cand_removes and not cand_still_has:
        return _result(pid, "correct", "spaceItems prop removed (now CSS gap)")
    if cand_still_has:
        return _result(pid, "missing", "spaceItems prop still present")
    return _not_applicable(pid)


def detect_ouia_component_id(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect OUIA component ID prop standardization."""
    pid = "ouia-component-id"
    if not ref_diff or not (_diff_removes_pattern(ref_diff, r"\bouiaId\b") or _diff_has_pattern(ref_diff, r"\bouiaId\b")):
        return _not_applicable(pid)

    cand_has_change = _diff_has_pattern(cand_diff, r"\bouiaId\b") or _diff_removes_pattern(cand_diff, r"\bouiaId\b")
    if cand_has_change:
        return _result(pid, "correct", "OUIA component ID props updated")
    return _result(pid, "missing", "OUIA component ID migration not applied")


def detect_chips_to_labels(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Chip/ChipGroup → Label/LabelGroup migration.

    Checks component renames (Chip→Label, ChipGroup→LabelGroup)
    and prop renames (chips→labels, deleteChip→deleteLabel).
    """
    pid = "chips-to-labels"
    if not ref_diff:
        return _not_applicable(pid)

    # Check for any chip-related removal in reference
    chip_patterns = [r"\bChip\b", r"\bChipGroup\b", r"\bchips\b", r"\bdeleteChip\b"]
    ref_removes_any = any(_diff_removes_pattern(ref_diff, p) for p in chip_patterns)
    if not ref_removes_any:
        return _not_applicable(pid)

    # Check candidate for both component and prop renames
    cand_removes_chip = any(_diff_removes_pattern(cand_diff, p) for p in chip_patterns)
    label_patterns = [r"\bLabel\b", r"\bLabelGroup\b", r"\blabels\b", r"\bdeleteLabel\b"]
    cand_adds_label = any(_diff_has_pattern(cand_diff, p) for p in label_patterns)

    # Check for residual old tokens in candidate content
    cand_still_chip = cand_content and (
        re.search(r"\bChip\b", cand_content) or
        re.search(r"\bChipGroup\b", cand_content) or
        re.search(r"\bdeleteChip\b", cand_content)
    )

    if (cand_removes_chip or cand_adds_label) and not cand_still_chip:
        return _result(pid, "correct", "Chip/ChipGroup migrated to Label/LabelGroup")
    if cand_still_chip and cand_adds_label:
        return _result(pid, "incorrect", "Partial migration — some Chip/ChipGroup/deleteChip references remain")
    if cand_still_chip:
        return _result(pid, "missing", "Chip/ChipGroup not migrated to Label/LabelGroup")
    return _not_applicable(pid)


def detect_split_button_items(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect splitButtonOptions → splitButtonItems prop rename."""
    pid = "split-button-items"
    if not ref_diff:
        return _not_applicable(pid)

    # Reference should show the rename
    ref_removes_old = _diff_removes_pattern(ref_diff, r"\bsplitButtonOptions\b")
    ref_adds_new = _diff_has_pattern(ref_diff, r"\bsplitButtonItems\b")
    if not (ref_removes_old or ref_adds_new):
        return _not_applicable(pid)

    cand_removes_old = _diff_removes_pattern(cand_diff, r"\bsplitButtonOptions\b")
    cand_adds_new = _diff_has_pattern(cand_diff, r"\bsplitButtonItems\b")
    cand_still_old = cand_content and re.search(r"\bsplitButtonOptions\b", cand_content)

    if (cand_removes_old or cand_adds_new) and not cand_still_old:
        return _result(pid, "correct", "splitButtonOptions renamed to splitButtonItems")
    if cand_still_old:
        return _result(pid, "missing", "splitButtonOptions not renamed to splitButtonItems")
    return _not_applicable(pid)


def detect_modal_import_path(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Modal import path change (react-core → react-core/next or deprecated)."""
    pid = "modal-import-path"
    if not ref_diff:
        return _not_applicable(pid)

    # Check if reference changes Modal imports
    ref_changes_modal = (
        _diff_removes_pattern(ref_diff, r"@patternfly/react-core.*Modal")
        or _diff_has_pattern(ref_diff, r"@patternfly/react-core/(next|deprecated).*Modal")
    )
    if not ref_changes_modal:
        return _not_applicable(pid)

    cand_changes = (
        _diff_has_pattern(cand_diff, r"@patternfly/react-core/(next|deprecated).*Modal")
        or _diff_removes_pattern(cand_diff, r"@patternfly/react-core.*Modal")
    )

    if cand_changes:
        return _result(pid, "correct", "Modal import path updated")
    return _result(pid, "missing", "Modal import path not updated")


# ---------------------------------------------------------------------------
# Moderate patterns (weight 2)
# ---------------------------------------------------------------------------

def detect_text_content_consolidation(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Text/TextContent/TextList → Content consolidation.

    Also checks associated prop renames: isVisited → isVisitedLink,
    isPlain → isPlainList.
    """
    pid = "text-content-consolidation"
    if not ref_diff:
        return _not_applicable(pid)

    old_components = r"\b(TextContent|TextList|TextListItem|TextVariants)\b"
    ref_removes_old = _diff_removes_pattern(ref_diff, old_components)
    ref_adds_content = _diff_has_pattern(ref_diff, r"\bContent\b")

    if not (ref_removes_old or ref_adds_content):
        return _not_applicable(pid)

    cand_removes = _diff_removes_pattern(cand_diff, old_components)
    cand_adds = _diff_has_pattern(cand_diff, r"\bContent\b")
    cand_still_old = cand_content and re.search(old_components, cand_content)

    if (cand_removes or cand_adds) and not cand_still_old:
        # Also check prop renames as quality signals
        issues: list[str] = []
        if _diff_has_pattern(ref_diff, r"\bisVisitedLink\b") or _diff_removes_pattern(ref_diff, r"\bisVisited\b"):
            if cand_content and re.search(r"\bisVisited\b", cand_content) and not re.search(r"\bisVisitedLink\b", cand_content):
                issues.append("isVisited not renamed to isVisitedLink")
        if _diff_has_pattern(ref_diff, r"\bisPlainList\b") or _diff_removes_pattern(ref_diff, r"\bisPlain\b"):
            if cand_content and re.search(r"\bisPlain\b", cand_content) and not re.search(r"\bisPlainList\b", cand_content):
                issues.append("isPlain not renamed to isPlainList")

        if issues:
            return _result(pid, "incorrect",
                           f"Text→Content done but missing prop renames: {'; '.join(issues)}")
        return _result(pid, "correct", "Text components consolidated to Content")
    if cand_still_old:
        return _result(pid, "missing" if not cand_adds else "incorrect",
                       "Old Text components still present")
    return _not_applicable(pid)


def detect_empty_state_restructure(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect EmptyState restructuring.

    PF6 replaces EmptyStateHeader/EmptyStateIcon child components
    with titleText/icon props on EmptyState.
    """
    pid = "empty-state-restructure"
    if not ref_diff:
        return _not_applicable(pid)

    # Check for old sub-components being removed in reference
    old_parts = r"\b(EmptyStateHeader|EmptyStateIcon|EmptyStateBody|EmptyStateSecondaryActions)\b"
    new_props = r"\b(titleText|headingLevel)\b"

    ref_removes_old = _diff_removes_pattern(ref_diff, old_parts)
    ref_adds_new = _diff_has_pattern(ref_diff, new_props) or _diff_has_pattern(ref_diff, r"\bEmptyStateActions\b")

    if not (ref_removes_old or ref_adds_new):
        return _not_applicable(pid)

    cand_still_old = cand_content and re.search(old_parts, cand_content)

    # AST check for new prop-based API
    if cand_tree is not None and cand_content:
        has_title_text = jsx_find_prop_on_component(cand_tree, cand_content, "EmptyState", "titleText")
        has_icon = jsx_find_prop_on_component(cand_tree, cand_content, "EmptyState", "icon")

        if (has_title_text or has_icon) and not cand_still_old:
            return _result(pid, "correct", "EmptyState restructured with titleText/icon props")
        if cand_still_old:
            return _result(pid, "incorrect" if (has_title_text or has_icon) else "missing",
                           "Old EmptyState sub-components still used")

    # Diff-based fallback
    cand_removes = _diff_removes_pattern(cand_diff, old_parts)
    cand_adds_new = _diff_has_pattern(cand_diff, new_props) or _diff_has_pattern(cand_diff, r"\bicon=")

    if (cand_removes or cand_adds_new) and not cand_still_old:
        return _result(pid, "correct", "EmptyState restructured to new API")
    if cand_still_old:
        return _result(pid, "missing", "Old EmptyState sub-components still used")
    return _not_applicable(pid)


def detect_toolbar_variant(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Toolbar variant prop changes.

    PF6 renames/removes specific variant values:
    - chip-group → label-group
    - bulk-select, overflow-menu, search-filter → removed
    Also checks ToolbarContent and ToolbarGroup variant usage.
    """
    pid = "toolbar-variant"
    if not ref_diff:
        return _not_applicable(pid)

    toolbar_context = (
        _diff_has_pattern(ref_diff, r"\bToolbar\b") or
        _diff_removes_pattern(ref_diff, r"\bToolbar\b") or
        _diff_has_pattern(ref_diff, r"\bToolbarContent\b") or
        _diff_has_pattern(ref_diff, r"\bToolbarGroup\b")
    )
    if not toolbar_context:
        return _not_applicable(pid)

    # Specific variant values that change in PF6
    old_variants = r"""variant=\s*["'{]*(chip-group|bulk-select|overflow-menu|search-filter)["'}]*"""
    new_variants = r"""variant=\s*["'{]*label-group["'}]*"""

    ref_removes_old = _diff_removes_pattern(ref_diff, old_variants)
    ref_adds_new = _diff_has_pattern(ref_diff, new_variants)
    ref_variant_change = ref_removes_old or ref_adds_new or _diff_removes_pattern(ref_diff, r"\bvariant=")

    if not ref_variant_change:
        return _not_applicable(pid)

    cand_removes_old = _diff_removes_pattern(cand_diff, old_variants)
    cand_adds_new = _diff_has_pattern(cand_diff, new_variants)
    cand_removes_variant = _diff_removes_pattern(cand_diff, r"\bvariant=")

    # Check for residual old variant values in candidate
    cand_still_old = cand_content and re.search(
        r"""variant=\s*["'{]*(chip-group|bulk-select|overflow-menu|search-filter)["'}]*""",
        cand_content,
    )

    if (cand_removes_old or cand_adds_new or cand_removes_variant) and not cand_still_old:
        return _result(pid, "correct", "Toolbar variant prop updated")
    if cand_still_old:
        return _result(pid, "incorrect", "Old Toolbar variant values still present (chip-group/bulk-select/etc.)")
    return _result(pid, "missing", "Toolbar variant prop not updated")


def detect_toolbar_gap(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect ToolbarGroup/ToolbarItem spacer → gap/columnGap/rowGap migration.

    PF6 replaces the spacer and spaceItems props on Toolbar components
    with standard CSS gap, columnGap, and rowGap props.
    """
    pid = "toolbar-gap"
    if not ref_diff:
        return _not_applicable(pid)

    toolbar_context = (
        _diff_has_pattern(ref_diff, r"\bToolbar\b") or
        _diff_removes_pattern(ref_diff, r"\bToolbar\b") or
        _diff_has_pattern(ref_diff, r"\bToolbarGroup\b") or
        _diff_has_pattern(ref_diff, r"\bToolbarItem\b")
    )
    spacer_change = (
        _diff_removes_pattern(ref_diff, r"\bspacer\b") or
        _diff_removes_pattern(ref_diff, r"\bspaceItems\b") or
        _diff_has_pattern(ref_diff, r"\bgap\b") or
        _diff_has_pattern(ref_diff, r"\bcolumnGap\b") or
        _diff_has_pattern(ref_diff, r"\browGap\b")
    )

    if not (spacer_change and toolbar_context):
        return _not_applicable(pid)

    cand_removes_old = (
        _diff_removes_pattern(cand_diff, r"\bspacer\b") or
        _diff_removes_pattern(cand_diff, r"\bspaceItems\b")
    )
    cand_adds_new = (
        _diff_has_pattern(cand_diff, r"\bgap\b") or
        _diff_has_pattern(cand_diff, r"\bcolumnGap\b") or
        _diff_has_pattern(cand_diff, r"\browGap\b")
    )
    # Check for residual old props in Toolbar context
    cand_still_spacer = cand_content and (
        re.search(r"\bspacer\b", cand_content) or
        re.search(r"\bspaceItems\b", cand_content)
    ) and re.search(r"\bToolbar\b", cand_content or "")

    if (cand_removes_old or cand_adds_new) and not cand_still_spacer:
        return _result(pid, "correct", "Toolbar spacer/spaceItems migrated to gap")
    if cand_still_spacer:
        return _result(pid, "missing", "Toolbar still uses spacer/spaceItems prop instead of gap")
    return _not_applicable(pid)


def detect_button_icon_prop(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Button icon prop migration (icon as child → icon prop).

    Applicability: the golden truth (ref) must use the ``icon=`` prop on
    Button.  We check the golden content directly rather than relying
    solely on the diff, since diff-based checks can false-trigger when
    the candidate uses the pattern but the golden truth does not.
    """
    pid = "button-icon-prop"
    if not ref_diff:
        return _not_applicable(pid)

    # Check golden truth content for the icon= prop pattern
    ref_uses_icon_prop = ref_content is not None and bool(re.search(r"\bicon\s*=", ref_content))
    # Also accept diff-based detection: golden truth adds icon= (+ lines in ref_diff)
    ref_adds_icon = _diff_has_pattern(ref_diff, r"\bicon=")

    if not (ref_uses_icon_prop or ref_adds_icon):
        return _not_applicable(pid)

    # Check if candidate also has the icon= prop
    cand_has_icon = cand_content is not None and bool(re.search(r"\bicon\s*=", cand_content))
    cand_icon_in_diff = _diff_has_pattern(cand_diff, r"\bicon=")

    if cand_has_icon or cand_icon_in_diff:
        return _result(pid, "correct", "Button icon prop migrated")
    return _result(pid, "missing", "Button icon prop migration not applied")


def detect_page_section_variant(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect PageSection variant prop changes.

    PF6 removes specific variant values:
    - variant="light" → removed (default)
    - variant="dark" → removed
    - variant="darker" → removed
    - PageSectionVariants enum → removed
    Also checks for type= prop removal.
    """
    pid = "page-section-variant"
    if not ref_diff or not (
        _diff_has_pattern(ref_diff, r"\bPageSection\b") or
        _diff_removes_pattern(ref_diff, r"\bPageSection\b")
    ):
        return _not_applicable(pid)

    # Check for specific variant values and the enum
    old_variant_values = r"""variant=\s*["'{]*(light|dark|darker)["'}]*"""
    old_enum = r"\bPageSectionVariants\b"

    ref_removes_variant = (
        _diff_removes_pattern(ref_diff, old_variant_values) or
        _diff_removes_pattern(ref_diff, old_enum) or
        _diff_removes_pattern(ref_diff, r"\bvariant=") or
        _diff_removes_pattern(ref_diff, r"\btype=")
    )
    if not ref_removes_variant:
        return _not_applicable(pid)

    cand_changes = (
        _diff_removes_pattern(cand_diff, old_variant_values) or
        _diff_removes_pattern(cand_diff, old_enum) or
        _diff_removes_pattern(cand_diff, r"\bvariant=") or
        _diff_removes_pattern(cand_diff, r"\btype=")
    )
    # Check for residual old variant values or enum in candidate
    cand_still_old = cand_content and (
        re.search(r"""variant=\s*["'{]*(light|dark|darker)["'}]*""", cand_content) or
        re.search(r"\bPageSectionVariants\b", cand_content) or
        re.search(r"PageSection[^>]*\btype=", cand_content)
    )

    if cand_changes and not cand_still_old:
        return _result(pid, "correct", "PageSection variant/type prop updated")
    if cand_still_old:
        return _result(pid, "incorrect" if cand_changes else "missing",
                       "Old PageSection variant values or PageSectionVariants enum still present")
    return _not_applicable(pid)


def detect_page_masthead(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect PageHeader → Masthead migration.

    Checks for:
    - PageHeader component → Masthead component
    - header prop on Page → masthead prop on Page
    """
    pid = "page-masthead"
    if not ref_diff:
        return _not_applicable(pid)

    ref_removes_header = _diff_removes_pattern(ref_diff, r"\bPageHeader\b")
    ref_adds_masthead = _diff_has_pattern(ref_diff, r"\bMasthead\b")
    # Also check for header→masthead prop rename on <Page>
    ref_renames_prop = (
        _diff_removes_pattern(ref_diff, r"\bheader=") and
        _diff_has_pattern(ref_diff, r"\bmasthead=")
    )

    if not (ref_removes_header or ref_adds_masthead or ref_renames_prop):
        return _not_applicable(pid)

    cand_removes_header = _diff_removes_pattern(cand_diff, r"\bPageHeader\b")
    cand_adds_masthead = _diff_has_pattern(cand_diff, r"\bMasthead\b")
    cand_renames_prop = (
        _diff_removes_pattern(cand_diff, r"\bheader=") and
        _diff_has_pattern(cand_diff, r"\bmasthead=")
    ) or _diff_has_pattern(cand_diff, r"\bmasthead=")

    cand_still_header = cand_content and (
        re.search(r"\bPageHeader\b", cand_content) or
        re.search(r"<Page[^>]+\bheader=", cand_content)
    )

    if (cand_removes_header or cand_adds_masthead or cand_renames_prop) and not cand_still_header:
        return _result(pid, "correct", "PageHeader migrated to Masthead (component and/or prop)")
    if cand_still_header:
        return _result(pid, "missing", "PageHeader or header= prop still used instead of Masthead/masthead=")
    return _not_applicable(pid)


def detect_react_tokens_icon_status(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect @patternfly/react-tokens and react-icons import changes.

    Tracks four categories:
    - react-tokens import path changes (e.g., dist/esm → dist/esm/...)
    - Old token format (global_*) → new format (t_*)
    - react-icons import path changes (@patternfly/react-icons → updated paths)
    - Icon component status token changes
    """
    pid = "react-tokens-icon-status"
    if not ref_diff:
        return _not_applicable(pid)

    # Check for any of the four categories in reference
    ref_changes_tokens = (
        _diff_removes_pattern(ref_diff, r"@patternfly/react-tokens") or
        _diff_has_pattern(ref_diff, r"@patternfly/react-tokens")
    )
    ref_changes_icons = (
        _diff_removes_pattern(ref_diff, r"@patternfly/react-icons") or
        _diff_has_pattern(ref_diff, r"@patternfly/react-icons")
    )
    ref_old_token_format = _diff_removes_pattern(ref_diff, r"\bglobal_\w+")
    ref_new_token_format = _diff_has_pattern(ref_diff, r"\bt_\w+")

    if not (ref_changes_tokens or ref_changes_icons or ref_old_token_format or ref_new_token_format):
        return _not_applicable(pid)

    issues: list[str] = []
    correct_count = 0
    total_applicable = 0

    # Check react-tokens imports
    if ref_changes_tokens:
        total_applicable += 1
        cand_changes_tokens = (
            _diff_removes_pattern(cand_diff, r"@patternfly/react-tokens") or
            _diff_has_pattern(cand_diff, r"@patternfly/react-tokens")
        )
        if cand_changes_tokens:
            correct_count += 1
        else:
            issues.append("react-tokens imports not updated")

    # Check react-icons imports
    if ref_changes_icons:
        total_applicable += 1
        cand_changes_icons = (
            _diff_removes_pattern(cand_diff, r"@patternfly/react-icons") or
            _diff_has_pattern(cand_diff, r"@patternfly/react-icons")
        )
        if cand_changes_icons:
            correct_count += 1
        else:
            issues.append("react-icons imports not updated")

    # Check old (global_) → new (t_) token format
    if ref_old_token_format or ref_new_token_format:
        total_applicable += 1
        cand_removes_old = _diff_removes_pattern(cand_diff, r"\bglobal_\w+")
        cand_adds_new = _diff_has_pattern(cand_diff, r"\bt_\w+")
        cand_still_old = cand_content and re.search(r"\bglobal_\w+", cand_content)

        if (cand_removes_old or cand_adds_new) and not cand_still_old:
            correct_count += 1
        elif cand_still_old:
            issues.append("Old token format (global_*) still used instead of new (t_*)")
        else:
            issues.append("Token format not migrated from global_* to t_*")

    if total_applicable == 0:
        return _not_applicable(pid)

    if correct_count == total_applicable:
        return _result(pid, "correct", "react-tokens/icons imports and token format updated")
    if correct_count > 0:
        return _result(pid, "incorrect",
                       f"Partial update: {'; '.join(issues)}")
    return _result(pid, "missing", f"Token/icon updates not applied: {'; '.join(issues)}")


def detect_avatar_adoption(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Avatar component prop changes (border, size, etc.)."""
    pid = "avatar-adoption"
    if not ref_diff or not (_diff_has_pattern(ref_diff, r"\bAvatar\b") or _diff_removes_pattern(ref_diff, r"\bAvatar\b")):
        return _not_applicable(pid)

    # Check for Avatar prop changes in reference
    ref_prop_change = (
        _diff_removes_pattern(ref_diff, r"\bborder=") or
        _diff_has_pattern(ref_diff, r"\bsize=") or
        _diff_removes_pattern(ref_diff, r"\bsize=")
    )
    if not ref_prop_change:
        return _not_applicable(pid)

    cand_changes_avatar = _diff_has_pattern(cand_diff, r"\bAvatar\b") or _diff_removes_pattern(cand_diff, r"\bAvatar\b")

    if cand_changes_avatar:
        return _result(pid, "correct", "Avatar props updated for PF6")
    return _result(pid, "missing", "Avatar prop changes not applied")


# ---------------------------------------------------------------------------
# Complex patterns (weight 3)
# ---------------------------------------------------------------------------

def detect_select_rewrite(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Select component rewrite (PF5 Select → PF6 composable Select).

    The PF6 Select is a completely different API. This uses AST analysis when
    available, otherwise falls back to diff heuristics.
    """
    pid = "select-rewrite"
    if not ref_diff:
        return _not_applicable(pid)

    # Check if reference involves Select changes
    ref_has_select = (
        _diff_has_pattern(ref_diff, r"\bSelect\b") or
        _diff_removes_pattern(ref_diff, r"\bSelect\b")
    )
    if not ref_has_select:
        return _not_applicable(pid)

    # AST-based detection if trees are available
    if cand_tree is not None and cand_content:
        components = jsx_find_components(cand_tree, cand_content)
        select_tags = [c for c in components if c["tag_name"] in ("Select", "MenuToggle", "SelectOption", "SelectList")]

        # PF6 composable Select uses MenuToggle as toggle
        has_menu_toggle = any(c["tag_name"] == "MenuToggle" for c in select_tags)
        has_select_list = any(c["tag_name"] == "SelectList" for c in select_tags)

        # Check imports for new path
        if cand_content:
            imports = find_imports(cand_tree, cand_content)
            uses_new_import = any(
                "react-core" in imp.get("module", "") and
                any(n in ("Select", "SelectOption", "SelectList", "MenuToggle")
                    for n in imp.get("named_imports", []))
                for imp in imports
            )
        else:
            uses_new_import = False

        if has_menu_toggle or has_select_list:
            return _result(pid, "correct", "Select rewritten to PF6 composable API with MenuToggle/SelectList")

        if uses_new_import and not has_menu_toggle:
            return _result(pid, "incorrect", "Select imports updated but not fully rewritten to composable API")

    # Diff-based fallback
    cand_has_select = _diff_has_pattern(cand_diff, r"\bSelect\b") or _diff_removes_pattern(cand_diff, r"\bSelect\b")
    cand_has_new_api = (
        _diff_has_pattern(cand_diff, r"\bMenuToggle\b") or
        _diff_has_pattern(cand_diff, r"\bSelectList\b")
    )

    # Check for old PF5 Select API props still present in candidate
    old_api_props = [r"\bonToggle\b", r"\bisOpen\b", r"\bselections\b", r"\bplaceholderText\b"]
    cand_still_old_api = cand_content and any(
        re.search(prop, cand_content) for prop in old_api_props
    )

    if cand_has_new_api and not cand_still_old_api:
        return _result(pid, "correct", "Select rewritten to PF6 composable API")
    if cand_has_new_api and cand_still_old_api:
        return _result(pid, "incorrect",
                       "Select partially rewritten — old API props (onToggle/isOpen/selections) still present")
    if cand_has_select and not cand_has_new_api:
        return _result(pid, "incorrect", "Select changed but not fully migrated to PF6 composable API")
    if not cand_has_select and ref_has_select:
        return _result(pid, "missing", "Select rewrite not applied")
    return _not_applicable(pid)


def detect_masthead_reorganization(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect Masthead sub-component reorganization (MastheadToggle, MastheadBrand, etc.)."""
    pid = "masthead-reorganization"
    if not ref_diff:
        return _not_applicable(pid)

    old_parts = r"\b(MastheadToggle|MastheadBrand|MastheadMain)\b"
    new_parts = r"\b(MastheadLogo|MastheadBrand)\b"

    ref_changes = _diff_removes_pattern(ref_diff, old_parts) or _diff_has_pattern(ref_diff, new_parts)
    if not ref_changes:
        return _not_applicable(pid)

    # AST-based detection
    if cand_tree is not None and cand_content:
        components = jsx_find_components(cand_tree, cand_content)
        comp_names = {c["tag_name"] for c in components}

        has_old = bool(comp_names & {"MastheadToggle"})
        has_new_structure = bool(comp_names & {"MastheadLogo", "MastheadBrand", "MastheadMain"})

        if has_new_structure and not has_old:
            return _result(pid, "correct", "Masthead sub-components reorganized for PF6")
        if has_old:
            return _result(pid, "missing", "Old Masthead sub-components still present")

    # Diff fallback
    cand_removes_old = _diff_removes_pattern(cand_diff, old_parts)
    cand_has_new = _diff_has_pattern(cand_diff, new_parts)

    if cand_removes_old or cand_has_new:
        return _result(pid, "correct", "Masthead reorganization applied")
    return _result(pid, "missing", "Masthead reorganization not applied")


def detect_test_selector_rewrite(
    ref_diff: str | None, cand_diff: str | None,
    ref_content: str | None, cand_content: str | None,
    ref_tree: Any, cand_tree: Any, **kwargs: Any,
) -> dict[str, Any]:
    """Detect test selector updates for PF6 class name changes.

    Tracks four sub-categories:
    - CSS selector changes (pf-v5- → pf-v6-)
    - data-testid attribute changes
    - aria-label attribute changes
    - Test query function changes (getByTestId, queryByRole, etc.)
    """
    pid = "test-selector-rewrite"
    path = kwargs.get("path", "")

    # Only applicable to test files
    if not re.search(r"\.(test|spec|cy)\.(tsx?|jsx?)$", path):
        return _not_applicable(pid)

    if not ref_diff:
        return _not_applicable(pid)

    issues: list[str] = []
    correct_count = 0
    total_applicable = 0

    # Sub-category 1: CSS selector changes (pf-v5- → pf-v6-)
    ref_css_selectors = (
        _diff_removes_pattern(ref_diff, r"pf-v5-") or
        _diff_has_pattern(ref_diff, r"pf-v6-") or
        _diff_has_pattern(ref_diff, r'querySelector.*pf-')
    )
    if ref_css_selectors:
        total_applicable += 1
        cand_css = (
            _diff_has_pattern(cand_diff, r"pf-v6-") or
            _diff_removes_pattern(cand_diff, r"pf-v5-")
        )
        cand_still_v5 = cand_content and re.search(r"pf-v5-", cand_content)
        if cand_css and not cand_still_v5:
            correct_count += 1
        else:
            issues.append("CSS selectors still reference pf-v5- classes")

    # Sub-category 2: data-testid changes
    ref_testid = (
        _diff_removes_pattern(ref_diff, r"data-testid") or
        _diff_has_pattern(ref_diff, r"data-testid")
    )
    if ref_testid:
        total_applicable += 1
        cand_testid = (
            _diff_removes_pattern(cand_diff, r"data-testid") or
            _diff_has_pattern(cand_diff, r"data-testid")
        )
        if cand_testid:
            correct_count += 1
        else:
            issues.append("data-testid attributes not updated")

    # Sub-category 3: aria-label changes
    ref_aria = (
        _diff_removes_pattern(ref_diff, r"aria-label") or
        _diff_has_pattern(ref_diff, r"aria-label")
    )
    if ref_aria:
        total_applicable += 1
        cand_aria = (
            _diff_removes_pattern(cand_diff, r"aria-label") or
            _diff_has_pattern(cand_diff, r"aria-label")
        )
        if cand_aria:
            correct_count += 1
        else:
            issues.append("aria-label attributes not updated")

    # Sub-category 4: Test query function changes
    query_fns = r"\b(getBy|queryBy|findBy|getAllBy|queryAllBy|findAllBy)(TestId|Role|LabelText|Text|PlaceholderText)\b"
    ref_queries = (
        _diff_removes_pattern(ref_diff, query_fns) or
        _diff_has_pattern(ref_diff, query_fns)
    )
    if ref_queries:
        total_applicable += 1
        cand_queries = (
            _diff_removes_pattern(cand_diff, query_fns) or
            _diff_has_pattern(cand_diff, query_fns)
        )
        if cand_queries:
            correct_count += 1
        else:
            issues.append("Test query functions not updated")

    if total_applicable == 0:
        return _not_applicable(pid)

    if correct_count == total_applicable:
        return _result(pid, "correct", "Test selectors fully updated for PF6")
    if correct_count > 0:
        return _result(pid, "incorrect",
                       f"Partial test selector update: {'; '.join(issues)}")
    return _result(pid, "missing", f"Test selector updates not applied: {'; '.join(issues)}")


# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------

def get_patterns() -> list[dict[str, Any]]:
    """Return all PatternFly 5→6 migration pattern definitions."""
    return [
        # Trivial (weight 1)
        {
            "id": "css-class-prefix",
            "name": "CSS Class Prefix (pf-v5- → pf-v6-)",
            "complexity": "trivial",
            "weight": 1,
            "description": "Update CSS class prefixes from pf-v5- to pf-v6-",
            "detect": detect_css_class_prefix,
        },
        {
            "id": "utility-class-rename",
            "name": "Utility Class Rename (pf-u-* → pf-v6-u-*)",
            "complexity": "trivial",
            "weight": 1,
            "description": "Rename PF utility classes to include version prefix",
            "detect": detect_utility_class_rename,
        },
        {
            "id": "css-logical-properties",
            "name": "CSS Logical Properties",
            "complexity": "trivial",
            "weight": 1,
            "description": "Adopt CSS logical properties (margin-left → margin-inline-start)",
            "detect": detect_css_logical_properties,
        },
        {
            "id": "theme-dark-removal",
            "name": "Theme Dark Class Removal",
            "complexity": "trivial",
            "weight": 1,
            "description": "Remove or update .pf-theme-dark usage",
            "detect": detect_theme_dark_removal,
        },
        {
            "id": "inner-ref-to-ref",
            "name": "innerRef → ref Prop",
            "complexity": "trivial",
            "weight": 1,
            "description": "Migrate innerRef prop to standard ref",
            "detect": detect_inner_ref_to_ref,
        },
        {
            "id": "align-right-to-end",
            "name": "Alignment right/left → end/start",
            "complexity": "trivial",
            "weight": 1,
            "description": "Update alignment prop values from 'right'/'left' to 'end'/'start'",
            "detect": detect_align_right_to_end,
        },
        {
            "id": "is-action-cell",
            "name": "isActionCell Prop Removal",
            "complexity": "trivial",
            "weight": 1,
            "description": "Remove deprecated isActionCell prop from Td",
            "detect": detect_is_action_cell,
        },
        {
            "id": "space-items-removal",
            "name": "spaceItems Prop Removal",
            "complexity": "trivial",
            "weight": 1,
            "description": "Remove spaceItems prop (replaced by CSS gap)",
            "detect": detect_space_items_removal,
        },
        {
            "id": "ouia-component-id",
            "name": "OUIA Component ID Standardization",
            "complexity": "trivial",
            "weight": 1,
            "description": "Update OUIA component ID props",
            "detect": detect_ouia_component_id,
        },
        {
            "id": "chips-to-labels",
            "name": "Chip/ChipGroup → Label/LabelGroup",
            "complexity": "trivial",
            "weight": 1,
            "description": "Migrate Chip and ChipGroup to Label and LabelGroup",
            "detect": detect_chips_to_labels,
        },
        {
            "id": "split-button-items",
            "name": "SplitButton Items",
            "complexity": "trivial",
            "weight": 1,
            "description": "Update SplitButton items API",
            "detect": detect_split_button_items,
        },
        {
            "id": "modal-import-path",
            "name": "Modal Import Path",
            "complexity": "trivial",
            "weight": 1,
            "description": "Update Modal import from react-core to react-core/next or deprecated",
            "detect": detect_modal_import_path,
        },
        # Moderate (weight 2)
        {
            "id": "text-content-consolidation",
            "name": "Text/TextContent → Content",
            "complexity": "moderate",
            "weight": 2,
            "description": "Consolidate Text, TextContent, TextList into Content component",
            "detect": detect_text_content_consolidation,
        },
        {
            "id": "empty-state-restructure",
            "name": "EmptyState Restructuring",
            "complexity": "moderate",
            "weight": 2,
            "description": "Restructure EmptyState from sub-components to composable API",
            "detect": detect_empty_state_restructure,
        },
        {
            "id": "toolbar-variant",
            "name": "Toolbar Variant Prop",
            "complexity": "moderate",
            "weight": 2,
            "description": "Update Toolbar variant prop usage",
            "detect": detect_toolbar_variant,
        },
        {
            "id": "toolbar-gap",
            "name": "Toolbar Spacer → Gap",
            "complexity": "moderate",
            "weight": 2,
            "description": "Migrate Toolbar spacer prop to CSS gap",
            "detect": detect_toolbar_gap,
        },
        {
            "id": "button-icon-prop",
            "name": "Button Icon Prop",
            "complexity": "moderate",
            "weight": 2,
            "description": "Migrate Button icon from child to icon prop",
            "detect": detect_button_icon_prop,
        },
        {
            "id": "page-section-variant",
            "name": "PageSection Variant/Type",
            "complexity": "moderate",
            "weight": 2,
            "description": "Update PageSection variant/type prop",
            "detect": detect_page_section_variant,
        },
        {
            "id": "page-masthead",
            "name": "PageHeader → Masthead",
            "complexity": "moderate",
            "weight": 2,
            "description": "Migrate PageHeader to Masthead component",
            "detect": detect_page_masthead,
        },
        {
            "id": "react-tokens-icon-status",
            "name": "React Tokens Import Updates",
            "complexity": "moderate",
            "weight": 2,
            "description": "Update @patternfly/react-tokens import paths",
            "detect": detect_react_tokens_icon_status,
        },
        {
            "id": "avatar-adoption",
            "name": "Avatar Prop Updates",
            "complexity": "moderate",
            "weight": 2,
            "description": "Update Avatar component props for PF6",
            "detect": detect_avatar_adoption,
        },
        # Complex (weight 3)
        {
            "id": "select-rewrite",
            "name": "Select Component Rewrite",
            "complexity": "complex",
            "weight": 3,
            "description": "Rewrite PF5 Select to PF6 composable Select with MenuToggle",
            "detect": detect_select_rewrite,
        },
        {
            "id": "masthead-reorganization",
            "name": "Masthead Reorganization",
            "complexity": "complex",
            "weight": 3,
            "description": "Reorganize Masthead sub-components for PF6 structure",
            "detect": detect_masthead_reorganization,
        },
        {
            "id": "test-selector-rewrite",
            "name": "Test Selector Rewrite",
            "complexity": "complex",
            "weight": 3,
            "description": "Update test selectors for PF6 class name changes",
            "detect": detect_test_selector_rewrite,
        },
    ]
