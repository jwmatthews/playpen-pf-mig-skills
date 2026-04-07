"""Comparison logic: before-vs-attempt and attempt-vs-attempt."""

from __future__ import annotations

from migeval.models import AttemptDelta, AttemptResult


def compare_attempts(a: AttemptResult, b: AttemptResult) -> AttemptDelta:
    """Compare two attempt results by issue IDs.

    Returns a delta showing resolved, new, and shared issues.
    """
    ids_a: set[str] = set()
    ids_b: set[str] = set()

    for lr in a.layer_results.values():
        for issue in lr.issues:
            ids_a.add(issue.id)

    for lr in b.layer_results.values():
        for issue in lr.issues:
            ids_b.add(issue.id)

    resolved = sorted(ids_a - ids_b)
    new = sorted(ids_b - ids_a)
    shared = sorted(ids_a & ids_b)

    return AttemptDelta(
        attempt_a=a.name,
        attempt_b=b.name,
        resolved=resolved,
        new=new,
        shared=shared,
        delta=len(new) - len(resolved),
    )
