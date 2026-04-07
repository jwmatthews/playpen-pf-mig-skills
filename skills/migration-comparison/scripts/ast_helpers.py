#!/usr/bin/env python3
"""
Tree-sitter wrapper for TSX/TS AST analysis.

Provides helpers used by pattern detectors in targets/ to inspect
JSX component names, props, imports, and nesting in TypeScript/TSX files.
"""

from __future__ import annotations

from typing import Any

try:
    import tree_sitter_typescript as ts_typescript
    from tree_sitter import Language, Parser, Node, Tree

    _TSX_LANGUAGE = Language(ts_typescript.language_tsx())
    _TS_LANGUAGE = Language(ts_typescript.language_typescript())
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    Tree = Any  # type: ignore[assignment,misc]
    Node = Any  # type: ignore[assignment,misc]


def is_available() -> bool:
    """Return True if tree-sitter and tree-sitter-typescript are installed."""
    return _AVAILABLE


def parse_tsx(content: str) -> Tree | None:
    """Parse TSX/TS content into a tree-sitter tree.

    Returns None if tree-sitter is not available.
    """
    if not _AVAILABLE:
        return None
    parser = Parser(_TSX_LANGUAGE)
    return parser.parse(content.encode("utf-8"))


def parse_ts(content: str) -> Tree | None:
    """Parse plain TS content (non-JSX) into a tree-sitter tree.

    Returns None if tree-sitter is not available.
    """
    if not _AVAILABLE:
        return None
    parser = Parser(_TS_LANGUAGE)
    return parser.parse(content.encode("utf-8"))


def _node_text(node: Node, source: bytes) -> str:
    """Extract the text content of a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def find_imports(tree: Tree, source: str) -> list[dict[str, Any]]:
    """Extract import declarations from a tree-sitter tree.

    Returns a list of dicts with:
      - module: str — the module specifier (e.g., '@patternfly/react-core')
      - named_imports: list[str] — named imports (e.g., ['Button', 'Alert'])
      - default_import: str | None — default import name
    """
    if tree is None:
        return []
    src = source.encode("utf-8")
    results: list[dict[str, Any]] = []
    root = tree.root_node

    for node in _walk(root):
        if node.type != "import_statement":
            continue

        module = None
        named_imports: list[str] = []
        default_import: str | None = None

        for child in node.children:
            if child.type == "string":
                module = _node_text(child, src).strip("'\"")
            elif child.type == "import_clause":
                for clause_child in child.children:
                    if clause_child.type == "identifier":
                        default_import = _node_text(clause_child, src)
                    elif clause_child.type == "named_imports":
                        for spec in clause_child.children:
                            if spec.type == "import_specifier":
                                name_node = spec.child_by_field_name("name")
                                if name_node:
                                    named_imports.append(_node_text(name_node, src))

        if module is not None:
            results.append({
                "module": module,
                "named_imports": named_imports,
                "default_import": default_import,
            })

    return results


def jsx_find_components(tree: Tree, source: str) -> list[dict[str, Any]]:
    """Extract JSX component tag names and their props from a tree.

    Returns a list of dicts with:
      - tag_name: str — the component name (e.g., 'Button', 'div')
      - props: list[dict] — each with 'name' and 'value' keys
      - children: list[str] — tag names of direct JSX children
      - node: the tree-sitter node (for further inspection)
    """
    if tree is None:
        return []
    src = source.encode("utf-8")
    results: list[dict[str, Any]] = []
    root = tree.root_node

    for node in _walk(root):
        if node.type not in ("jsx_element", "jsx_self_closing_element"):
            continue

        tag_name: str | None = None
        props: list[dict[str, str | None]] = []
        children: list[str] = []

        if node.type == "jsx_self_closing_element":
            for child in node.children:
                if child.type in ("identifier", "member_expression", "nested_identifier"):
                    tag_name = _node_text(child, src)
                elif child.type == "jsx_attribute":
                    prop = _jsx_extract_attribute(child, src)
                    if prop:
                        props.append(prop)
        elif node.type == "jsx_element":
            opening = node.child_by_field_name("open_tag")
            if opening is None:
                # fallback: look for jsx_opening_element
                for child in node.children:
                    if child.type == "jsx_opening_element":
                        opening = child
                        break
            if opening:
                for child in opening.children:
                    if child.type in ("identifier", "member_expression", "nested_identifier"):
                        tag_name = _node_text(child, src)
                    elif child.type == "jsx_attribute":
                        prop = _jsx_extract_attribute(child, src)
                        if prop:
                            props.append(prop)

            # Direct JSX children
            for child in node.children:
                if child.type == "jsx_element":
                    child_opening = child.child_by_field_name("open_tag")
                    if child_opening is None:
                        for cc in child.children:
                            if cc.type == "jsx_opening_element":
                                child_opening = cc
                                break
                    if child_opening:
                        for cc in child_opening.children:
                            if cc.type in ("identifier", "member_expression", "nested_identifier"):
                                children.append(_node_text(cc, src))
                elif child.type == "jsx_self_closing_element":
                    for cc in child.children:
                        if cc.type in ("identifier", "member_expression", "nested_identifier"):
                            children.append(_node_text(cc, src))

        if tag_name:
            results.append({
                "tag_name": tag_name,
                "props": props,
                "children": children,
                "node": node,
            })

    return results


def jsx_find_prop_on_component(
    tree: Tree, source: str, component_name: str, prop_name: str
) -> bool:
    """Check if a specific prop exists on any instance of a JSX component."""
    components = jsx_find_components(tree, source)
    for comp in components:
        if comp["tag_name"] == component_name:
            for prop in comp["props"]:
                if prop["name"] == prop_name:
                    return True
    return False


def jsx_get_children(tree: Tree, source: str, component_name: str) -> list[str]:
    """Get tag names of direct JSX children for instances of a JSX component."""
    components = jsx_find_components(tree, source)
    children: list[str] = []
    for comp in components:
        if comp["tag_name"] == component_name:
            children.extend(comp["children"])
    return children


def find_string_literals(tree: Tree, source: str, pattern: str | None = None) -> list[str]:
    """Find string literal values in the tree, optionally matching a substring pattern."""
    if tree is None:
        return []
    src = source.encode("utf-8")
    results: list[str] = []
    for node in _walk(tree.root_node):
        if node.type in ("string", "template_string"):
            text = _node_text(node, src).strip("'\"`")
            if pattern is None or pattern in text:
                results.append(text)
    return results


def _jsx_extract_attribute(node: Node, src: bytes) -> dict[str, str | None] | None:
    """Extract name and value from a jsx_attribute node."""
    name: str | None = None
    value: str | None = None
    for child in node.children:
        if child.type == "property_identifier":
            name = _node_text(child, src)
        elif child.type in ("string", "jsx_expression", "true", "false"):
            value = _node_text(child, src)
    if name is None:
        return None
    return {"name": name, "value": value}


def _walk(node: Node) -> list[Node]:
    """Recursively walk all nodes in a tree-sitter tree (pre-order)."""
    result: list[Node] = [node]
    for child in node.children:
        result.extend(_walk(child))
    return result
