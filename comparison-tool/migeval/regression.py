"""Regression tracking: compare current run to a previous run."""

from __future__ import annotations

from migeval.models import EvaluationRun, Issue, RegressionItem


def compute_regressions(
    current: EvaluationRun,
    previous: EvaluationRun,
) -> list[RegressionItem]:
    """Compare two evaluation runs and identify regressions.

    Matches attempts by name across runs.
    """
    items: list[RegressionItem] = []

    # Compare matching attempts
    for name in current.attempts:
        if name not in previous.attempts:
            continue

        curr_attempt = current.attempts[name]
        prev_attempt = previous.attempts[name]

        curr_issues: dict[str, Issue] = {}
        for lr in curr_attempt.layer_results.values():
            for issue in lr.issues:
                curr_issues[issue.id] = issue

        prev_issues: dict[str, Issue] = {}
        for lr in prev_attempt.layer_results.values():
            for issue in lr.issues:
                prev_issues[issue.id] = issue

        # New issues (in current but not previous)
        for issue_id, issue in curr_issues.items():
            if issue_id not in prev_issues:
                items.append(
                    RegressionItem(
                        issue_id=issue_id,
                        status="new",
                        current=issue,
                        detail=f"New issue in {name}: {issue.title}",
                    )
                )

        # Resolved issues (in previous but not current)
        for issue_id, issue in prev_issues.items():
            if issue_id not in curr_issues:
                items.append(
                    RegressionItem(
                        issue_id=issue_id,
                        status="resolved",
                        previous=issue,
                        detail=f"Resolved in {name}: {issue.title}",
                    )
                )

        # Changed issues (in both but severity changed)
        for issue_id in curr_issues.keys() & prev_issues.keys():
            curr = curr_issues[issue_id]
            prev = prev_issues[issue_id]
            if curr.severity != prev.severity:
                items.append(
                    RegressionItem(
                        issue_id=issue_id,
                        status="changed",
                        current=curr,
                        previous=prev,
                        detail=(
                            f"Severity changed in {name}: "
                            f"{prev.severity} -> {curr.severity}"
                        ),
                    )
                )

    return items
