from __future__ import annotations

from pipeline_coach.hygiene.priority import compute_priority

from pipeline_coach.models import Issue


def _issue(severity: str, rule_id: str = "test_rule") -> Issue:
    return Issue(rule_id=rule_id, severity=severity, message="test")  # type: ignore[arg-type]


def test_high_severity_returns_high() -> None:
    issues = [_issue("high")]
    assert compute_priority(issues) == "high"


def test_medium_severity_only_returns_medium() -> None:
    issues = [_issue("medium")]
    assert compute_priority(issues) == "medium"


def test_low_severity_only_returns_low() -> None:
    issues = [_issue("low")]
    assert compute_priority(issues) == "low"


def test_worst_issue_wins_low_and_high_returns_high() -> None:
    issues = [_issue("low", "rule_a"), _issue("high", "rule_b")]
    assert compute_priority(issues) == "high"


def test_empty_issues_returns_low() -> None:
    assert compute_priority([]) == "low"


def test_large_amount_late_stage_medium_stays_medium() -> None:
    issues = [_issue("medium")]
    assert compute_priority(issues, amount=500_000.0, stage="Negotiation") == "medium"
