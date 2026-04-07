"""JSON report output."""

from __future__ import annotations

import json
from pathlib import Path

from migeval.models import EvaluationRun


def write_json_report(run: EvaluationRun, path: Path) -> None:
    """Write the evaluation run as a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(run.model_dump(mode="json"), f, indent=2, default=str)
