#!/usr/bin/env python3
"""
Add hasNoBodyWrapper to deprecated Modal components with composable children.

After pf-codemods moves Modal to @patternfly/react-core/deprecated, files that
use composable children (ModalHeader, ModalBody, ModalFooter) from
@patternfly/react-core need hasNoBodyWrapper on the deprecated <Modal>.
Without it, the deprecated Modal wraps all children in an extra ModalBoxBody
div, causing ~60px vertical layout shifts.

This script finds affected files and adds hasNoBodyWrapper automatically.

Usage:
  python3 fix_deprecated_modal_wrapper.py <project_path>
"""

import sys
import re
import json
from pathlib import Path

# Match import of Modal from deprecated path
DEPRECATED_MODAL_IMPORT = re.compile(
    r"""from\s+['"]@patternfly/react-core/deprecated['"]"""
)

# Match import of composable children from @patternfly/react-core
COMPOSABLE_CHILDREN_IMPORT = re.compile(
    r"""from\s+['"]@patternfly/react-core['"]"""
)
COMPOSABLE_CHILDREN_NAMES = re.compile(
    r'\b(ModalHeader|ModalBody|ModalFooter)\b'
)

# Match <Modal that does NOT already have hasNoBodyWrapper
MODAL_OPEN_TAG = re.compile(
    r'(<Modal\b(?![^>]*hasNoBodyWrapper)[^>]*)(>)'
)


def find_affected_files(project_path):
    """Find .tsx/.jsx files that use deprecated Modal with composable children."""
    project = Path(project_path)
    affected = []

    for ext in ('*.tsx', '*.jsx'):
        for filepath in project.rglob(ext):
            # Skip node_modules and build output
            parts = filepath.parts
            if 'node_modules' in parts or 'dist' in parts or 'build' in parts:
                continue

            try:
                content = filepath.read_text(encoding='utf-8')
            except (UnicodeDecodeError, PermissionError):
                continue

            has_deprecated_modal = bool(DEPRECATED_MODAL_IMPORT.search(content))
            if not has_deprecated_modal:
                continue

            # Check the deprecated import actually includes Modal
            # Find all imports from deprecated path and check for Modal
            imports_modal = False
            for line in content.split('\n'):
                if DEPRECATED_MODAL_IMPORT.search(line) and 'Modal' in line:
                    # Make sure it's Modal itself, not ModalVariant etc. only
                    # Simple check: "Modal" as a word boundary in the import
                    if re.search(r'\bModal\b', line.split('from')[0]):
                        imports_modal = True
                        break

            if not imports_modal:
                continue

            # Check for composable children imports from @patternfly/react-core
            has_composable = False
            for line in content.split('\n'):
                if COMPOSABLE_CHILDREN_IMPORT.search(line) and COMPOSABLE_CHILDREN_NAMES.search(line):
                    has_composable = True
                    break

            if not has_composable:
                continue

            # Check if any <Modal> tag is missing hasNoBodyWrapper
            if MODAL_OPEN_TAG.search(content):
                affected.append(filepath)

    return affected


def fix_file(filepath):
    """Add hasNoBodyWrapper to <Modal> tags missing it."""
    content = filepath.read_text(encoding='utf-8')
    new_content = MODAL_OPEN_TAG.sub(r'\1 hasNoBodyWrapper\2', content)
    if new_content != content:
        filepath.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <project_path>", file=sys.stderr)
        sys.exit(1)

    project_path = sys.argv[1]
    if not Path(project_path).is_dir():
        print(f"Error: {project_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    affected = find_affected_files(project_path)

    fixed = []
    for filepath in affected:
        if fix_file(filepath):
            fixed.append(str(filepath))

    result = {
        'project_path': project_path,
        'files_scanned': 'all .tsx/.jsx (excluding node_modules, dist, build)',
        'files_needing_fix': len(affected),
        'files_fixed': len(fixed),
        'fixed_files': fixed,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
