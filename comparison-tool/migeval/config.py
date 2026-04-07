"""Configuration loading for targets and projects."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from migeval.models import (
    BuildConfig,
    DependencyConfig,
    DependencyExpectation,
    DocRef,
    ProjectConfig,
    RouteConfig,
    RuntimeConfig,
    TargetConfig,
    TextPattern,
)


def load_target_config(target_dir: Path) -> TargetConfig:
    """Load a TargetConfig from a target directory containing target.yaml."""
    yaml_path = target_dir / "target.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"target.yaml not found in {target_dir}")

    with open(yaml_path) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    text_patterns: list[TextPattern] = []
    for p in raw.get("text_patterns", []):
        text_patterns.append(TextPattern(**p))

    deps: DependencyConfig | None = None
    if "dependencies" in raw:
        dep_raw = raw["dependencies"]
        expected = [DependencyExpectation(**e) for e in dep_raw.get("expected", [])]
        deps = DependencyConfig(expected=expected)

    build: BuildConfig | None = None
    if "build" in raw:
        build = BuildConfig(**raw["build"])

    runtime: RuntimeConfig | None = None
    if "runtime" in raw:
        runtime = RuntimeConfig(**raw["runtime"])

    routes: list[RouteConfig] = []
    for r in raw.get("routes", []):
        routes.append(RouteConfig(**r))

    docs: list[DocRef] = []
    for d in raw.get("docs", []):
        docs.append(DocRef(**d))

    return TargetConfig(
        target_dir=target_dir,
        name=raw.get("name", target_dir.name),
        framework=raw.get("framework", ""),
        dependencies=deps,
        text_patterns=text_patterns,
        build=build,
        runtime=runtime,
        routes=routes,
        docs=docs,
    )


def load_project_config(config_path: Path) -> ProjectConfig:
    """Load a ProjectConfig from a YAML file."""
    with open(config_path) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    build: BuildConfig | None = None
    if "build" in raw:
        build = BuildConfig(**raw["build"])

    runtime: RuntimeConfig | None = None
    if "runtime" in raw:
        runtime = RuntimeConfig(**raw["runtime"])

    routes: list[RouteConfig] = []
    for r in raw.get("routes", []):
        routes.append(RouteConfig(**r))

    return ProjectConfig(
        project=raw.get("project"),
        build=build,
        runtime=runtime,
        routes=routes,
        hints=raw.get("hints", ""),
    )


def resolve_target(
    target_name: str | None,
    target_dir: str | None,
) -> TargetConfig:
    """Resolve a target by name (bundled) or directory path (external)."""
    if target_dir:
        path = Path(target_dir)
        if not path.is_dir():
            raise FileNotFoundError(f"Target directory not found: {target_dir}")
        return load_target_config(path)

    if target_name:
        # Look in bundled targets/ directory (sibling to migeval package)
        pkg_dir = Path(__file__).parent.parent
        bundled = pkg_dir / "targets" / target_name
        if bundled.is_dir():
            return load_target_config(bundled)
        raise FileNotFoundError(
            f"Bundled target '{target_name}' not found at {bundled}"
        )

    raise ValueError("Either --target or --target-dir must be specified")


def merge_configs(
    target: TargetConfig,
    project: ProjectConfig | None,
) -> TargetConfig:
    """Merge project config overrides into target config.

    Project config values take precedence over target config.
    Returns a new TargetConfig with merged values.
    """
    if project is None:
        return target

    return target.model_copy(
        update={
            "build": project.build or target.build,
            "runtime": project.runtime or target.runtime,
            "routes": project.routes if project.routes else target.routes,
        }
    )


def load_target_module(target_dir: Path, module_name: str) -> ModuleType | None:
    """Dynamically load a Python module from a target directory.

    Returns None if the module file doesn't exist.
    """
    module_path = target_dir / f"{module_name}.py"
    if not module_path.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        f"migeval_target_{module_name}", module_path
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
