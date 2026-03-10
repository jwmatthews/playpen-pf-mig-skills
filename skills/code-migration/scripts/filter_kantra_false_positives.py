#!/usr/bin/env python3
"""
Filter known false positives from Kantra output before the agent sees them.

This script removes rules matching known false positive patterns from Kantra's
output.yaml, producing a filtered version. The agent only sees real issues,
eliminating wasted time re-verifying false positives against type definitions.

Usage:
  python3 filter_kantra_false_positives.py <input_yaml> [<output_yaml>]

If output_yaml is omitted, the filtered output is written to
<input_dir>/output.filtered.yaml and a summary is printed to stdout.
"""

import yaml
import sys
import json
import re
from pathlib import Path

# Known false positive rule patterns for PatternFly 6.
# Each entry is a regex that matches against the rule_id and/or description.
# These have been verified against PF6 type definitions and confirmed as false positives.
KNOWN_FALSE_POSITIVES = [
    # Matches ANY header JSX prop, not just Page.header
    r"header.*masthead",
    # PF6 barrel imports work correctly
    r"deep.import|import.path.restructur",
    # Props that still exist in PF6 types
    r"isOpen.*(?:open|should)",
    r"isDisabled.*disabled",
    r"isExpanded.*expanded",
    r"isSelected.*(?:removal|remove)",
    r"isActive.*active",
    # Flex props still supported
    r"spaceItems.*(?:removal|remove)",
    r"spacer.*gap",
    # Button variants still exist
    r"ButtonVariant\.link",
    r"ButtonVariant\.control",
    # FlexItem align still accepts alignRight
    r"alignRight.*alignEnd",
    # Matches title on ModalHeader (correct API), not deprecated Modal.title
    r"Modal.*title.*titleText",
    r"title.*titleText.*Modal",
    # Often custom project components, not PF's ErrorState
    r"ErrorState.*prop",
    # Often already using correct PF6 API
    r"CardHeader.*selectableActions",
    # Often already migrated by pf-codemods
    r"ToolbarFilter.*chips.*labels",
    r"chips.*labels.*ToolbarFilter",
]

# Compile patterns once
_FP_PATTERNS = [re.compile(p, re.IGNORECASE) for p in KNOWN_FALSE_POSITIVES]


def is_false_positive(rule_id, description):
    """Check if a rule matches any known false positive pattern."""
    text = f"{rule_id} {description}"
    return any(p.search(text) for p in _FP_PATTERNS)


def filter_kantra_output(input_path, output_path=None):
    """Filter known false positives from Kantra output.yaml.

    Returns a dict with filtering statistics.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        print(f"Error: Expected list of rulesets, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)

    total_rules = 0
    removed_rules = 0
    removed_details = []

    for ruleset in data:
        if not isinstance(ruleset, dict) or 'violations' not in ruleset:
            continue

        violations = ruleset.get('violations')
        if not isinstance(violations, dict):
            continue

        to_remove = []
        for rule_id, violation in violations.items():
            total_rules += 1
            description = violation.get('description', '') if isinstance(violation, dict) else ''
            if is_false_positive(rule_id, description):
                to_remove.append(rule_id)
                incident_count = len(violation.get('incidents', [])) if isinstance(violation, dict) else 0
                removed_details.append({
                    'rule_id': rule_id,
                    'description': description[:100],
                    'incidents': incident_count,
                })

        for rule_id in to_remove:
            del violations[rule_id]
            removed_rules += 1

    # Write filtered output
    if output_path is None:
        output_path = input_path.parent / 'output.filtered.yaml'
    else:
        output_path = Path(output_path)

    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False)

    # Write removal log next to output
    log_path = output_path.parent / 'false-positives-removed.json'
    log_data = {
        'total_rules_seen': total_rules,
        'false_positives_removed': removed_rules,
        'remaining_rules': total_rules - removed_rules,
        'removed': removed_details,
    }
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, indent=2)

    # Print summary to stdout
    summary = {
        'input': str(input_path),
        'output': str(output_path),
        'log': str(log_path),
        'total_rules': total_rules,
        'false_positives_removed': removed_rules,
        'remaining_rules': total_rules - removed_rules,
    }
    print(json.dumps(summary, indent=2))
    return summary


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.yaml> [<output.yaml>]", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    filter_kantra_output(input_path, output_path)


if __name__ == "__main__":
    main()
