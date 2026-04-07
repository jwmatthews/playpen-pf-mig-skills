"""Source evaluation layer.

Scans source files for text pattern matches, checks dependencies,
runs optional detectors, and parses violations.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from migeval.config import load_target_module
from migeval.models import (
    Issue,
    LayerContext,
    LayerName,
    LayerResult,
    ProjectConfig,
    Severity,
    TargetConfig,
    TextPattern,
    make_issue_id,
)
from migeval.util.file_enum import enumerate_files


class SourceLayer:
    """Scans source code for migration issues."""

    name: LayerName = "source"

    def can_run(
        self,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> tuple[bool, str]:
        """Source layer always runs — no external dependencies."""
        return True, ""

    def evaluate(
        self,
        path: Path,
        target: TargetConfig,
        project: ProjectConfig | None,
        context: LayerContext,
    ) -> LayerResult:
        """Run source evaluation: text patterns, deps, detectors, violations."""
        start = time.monotonic()
        issues: list[Issue] = []
        metadata: dict[str, Any] = {}

        # 1. Text pattern scan
        pattern_matches = self._scan_patterns(path, target.text_patterns)
        issues.extend(pattern_matches)
        metadata["text_matches"] = len(pattern_matches)

        # 2. Dependency check
        dep_issues = self._check_dependencies(path, target)
        issues.extend(dep_issues)
        if target.dependencies:
            total_deps = len(target.dependencies.expected)
            correct_deps = total_deps - len(dep_issues)
            metadata["deps_ok"] = correct_deps
            metadata["deps_total"] = total_deps

        # 3. Optional detectors
        detector_issues = self._run_detectors(path, target)
        issues.extend(detector_issues)
        metadata["detector_issues"] = len(detector_issues)

        # 4. Violation parse
        violation_issues = self._parse_violations(context)
        issues.extend(violation_issues)
        metadata["violation_issues"] = len(violation_issues)

        elapsed = time.monotonic() - start
        return LayerResult(
            layer="source",
            success=True,
            duration_seconds=round(elapsed, 2),
            issues=issues,
            metadata=metadata,
        )

    def _scan_patterns(
        self,
        root: Path,
        patterns: list[TextPattern],
    ) -> list[Issue]:
        """Scan files for text pattern matches."""
        issues: list[Issue] = []

        for pattern_def in patterns:
            compiled = re.compile(pattern_def.pattern)
            exclude_re = (
                re.compile(pattern_def.exclude_on_line)
                if pattern_def.exclude_on_line
                else None
            )
            files = enumerate_files(root, pattern_def.extensions or None)

            for file_path in files:
                try:
                    content = file_path.read_text(errors="replace")
                except OSError:
                    continue

                for line_num, line in enumerate(content.splitlines(), 1):
                    if not compiled.search(line):
                        continue
                    if exclude_re and exclude_re.search(line):
                        continue

                    rel_path = str(file_path.relative_to(root))
                    issue_id = make_issue_id(
                        "source_match", pattern_def.id, rel_path
                    )

                    # Deduplicate: one issue per (pattern, file)
                    if any(i.id == issue_id for i in issues):
                        continue

                    issues.append(
                        Issue(
                            id=issue_id,
                            source="source_match",
                            severity=pattern_def.severity,
                            file=rel_path,
                            line=line_num,
                            title=pattern_def.title,
                            detail=f"Pattern '{pattern_def.pattern}' matched",
                            evidence=line.strip()[:200],
                            suggestion=pattern_def.suggestion,
                            pattern_id=pattern_def.id,
                        )
                    )

        return issues

    def _check_dependencies(
        self,
        root: Path,
        target: TargetConfig,
    ) -> list[Issue]:
        """Check package.json dependencies against expected versions."""
        if not target.dependencies:
            return []

        pkg_json = root / "package.json"
        if not pkg_json.exists():
            return []

        try:
            with open(pkg_json) as f:
                pkg: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        all_deps: dict[str, str] = {}
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            deps_section = pkg.get(section)
            if isinstance(deps_section, dict):
                all_deps.update(deps_section)

        issues: list[Issue] = []
        for expected in target.dependencies.expected:
            installed = all_deps.get(expected.name)
            if installed is None:
                issues.append(
                    Issue(
                        id=make_issue_id("source_dependency", expected.name),
                        source="source_dependency",
                        severity="warning",
                        file="package.json",
                        title=f"Missing dependency: {expected.name}",
                        detail=(
                            f"Expected {expected.name} {expected.version}"
                            " but not found"
                        ),
                        suggestion=f"Add {expected.name}@{expected.version}",
                    )
                )
            elif not _version_matches(installed, expected.version):
                issues.append(
                    Issue(
                        id=make_issue_id("source_dependency", expected.name),
                        source="source_dependency",
                        severity="warning",
                        file="package.json",
                        title=f"Wrong version: {expected.name}",
                        detail=f"Expected {expected.version}, found {installed}",
                        suggestion=f"Update to {expected.name}@{expected.version}",
                    )
                )

        return issues

    def _run_detectors(
        self,
        root: Path,
        target: TargetConfig,
    ) -> list[Issue]:
        """Run optional Python detectors from the target."""
        module = load_target_module(target.target_dir, "detectors")
        if module is None:
            return []

        detect_fn = getattr(module, "detect", None)
        if detect_fn is None:
            return []

        results: list[Any] = detect_fn(root)
        issues: list[Issue] = []
        for r in results:
            if isinstance(r, Issue):
                issues.append(r)
            elif isinstance(r, dict):
                issues.append(Issue(**r))

        return issues

    def _parse_violations(self, context: LayerContext) -> list[Issue]:
        """Parse violations from LayerContext (kantra/semver output)."""
        if not context.violations:
            return []

        issues: list[Issue] = []
        violations_data = context.violations

        # Handle kantra output.yaml format (list of rulesets with violations)
        if isinstance(violations_data, list):
            for entry in violations_data:
                if not isinstance(entry, dict):
                    continue
                for rule_id, violation in entry.get("violations", {}).items():
                    if not isinstance(violation, dict):
                        continue
                    for incident in violation.get("incidents", []):
                        file_uri = incident.get("uri", "")
                        file_path = _uri_to_path(file_uri)
                        issues.append(
                            Issue(
                                id=make_issue_id(
                                    "source_violation", rule_id, file_path
                                ),
                                source="source_violation",
                                severity=_kantra_category_to_severity(
                                    violation.get("category", "potential")
                                ),
                                file=file_path,
                                line=incident.get("lineNumber"),
                                title=violation.get(
                                    "description", rule_id
                                )[:100],
                                detail=incident.get("message", ""),
                                evidence=incident.get("codeSnip", "")[:500],
                            )
                        )

        return issues


def _version_matches(installed: str, expected: str) -> bool:
    """Check if an installed version satisfies the expected version spec.

    Simple check: if expected starts with ^, check major version matches.
    """
    installed = installed.lstrip("^~>=<")
    expected = expected.lstrip("^~>=<")

    installed_major = installed.split(".")[0] if installed else ""
    expected_major = expected.split(".")[0] if expected else ""

    return installed_major == expected_major


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a relative path."""
    if uri.startswith("file://"):
        return uri[7:]
    return uri


def _kantra_category_to_severity(category: str) -> Severity:
    """Map kantra violation category to severity."""
    mapping: dict[str, Severity] = {
        "mandatory": "high",
        "optional": "medium",
        "potential": "info",
    }
    return mapping.get(category, "warning")
