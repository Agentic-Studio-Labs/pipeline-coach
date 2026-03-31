from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from pipeline_coach.models import (
    SEVERITY_RANK,
    Brief,
    Issue,
    IssueSummary,
    OpportunityContext,
)

# ---------------------------------------------------------------------------
# SEVERITY_RANK
# ---------------------------------------------------------------------------


def test_severity_rank_values() -> None:
    assert SEVERITY_RANK["high"] == 3
    assert SEVERITY_RANK["medium"] == 2
    assert SEVERITY_RANK["low"] == 1


def test_severity_rank_only_three_keys() -> None:
    assert set(SEVERITY_RANK.keys()) == {"high", "medium", "low"}


# ---------------------------------------------------------------------------
# OpportunityContext
# ---------------------------------------------------------------------------


def test_opportunity_context_all_fields() -> None:
    opp = OpportunityContext(
        id="opp-1",
        name="Acme Deal",
        amount=50_000.0,
        stage="Negotiation",
        owner_email="alice@demo.com",
        owner_name="Alice",
        company_name="Acme Corp",
        close_date=date(2026, 6, 30),
        last_activity_at=datetime(2026, 3, 28, 10, 0),
        days_in_stage=14,
        days_since_last_activity=3,
        has_decision_maker=True,
    )
    assert opp.id == "opp-1"
    assert opp.amount == 50_000.0
    assert opp.close_date == date(2026, 6, 30)
    assert opp.has_decision_maker is True


def test_opportunity_context_minimal_fields() -> None:
    opp = OpportunityContext(
        id="opp-min",
        name="Minimal Deal",
        stage="Discovery",
        owner_email="bob@demo.com",
    )
    assert opp.id == "opp-min"
    assert opp.amount is None
    assert opp.owner_name is None
    assert opp.company_name is None
    assert opp.close_date is None
    assert opp.last_activity_at is None
    assert opp.days_in_stage is None
    assert opp.days_since_last_activity is None
    assert opp.has_decision_maker is None


def test_opportunity_context_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        OpportunityContext(  # type: ignore[call-arg]
            name="No ID Deal",
            stage="Discovery",
            owner_email="bob@demo.com",
        )


def test_opportunity_context_serialization_round_trip() -> None:
    opp = OpportunityContext(
        id="opp-rt",
        name="Round Trip",
        amount=99.99,
        stage="Proposal",
        owner_email="rt@demo.com",
        close_date=date(2026, 12, 31),
        last_activity_at=datetime(2026, 3, 1, 9, 0),
        days_in_stage=5,
        days_since_last_activity=1,
        has_decision_maker=False,
    )
    data = opp.model_dump()
    restored = OpportunityContext(**data)
    assert restored == opp


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------


def test_issue_all_fields() -> None:
    issue = Issue(
        rule_id="close_date_past",
        severity="high",
        message="Close date is in the past",
        details={"close_date": "2026-03-01", "days_overdue": 29},
    )
    assert issue.rule_id == "close_date_past"
    assert issue.severity == "high"
    assert issue.details["days_overdue"] == 29


def test_issue_invalid_severity_raises() -> None:
    with pytest.raises(ValidationError):
        Issue(
            rule_id="bad_severity",
            severity="critical",  # type: ignore[arg-type]
            message="This should fail",
        )


def test_issue_empty_details_default() -> None:
    issue = Issue(
        rule_id="no_details",
        severity="low",
        message="No extra details",
    )
    assert issue.details == {}


def test_issue_details_accepts_mixed_value_types() -> None:
    issue = Issue(
        rule_id="mixed",
        severity="medium",
        message="Mixed types",
        details={"label": "val", "count": 5, "ratio": 0.5, "flag": True, "nothing": None},
    )
    assert issue.details["label"] == "val"
    assert issue.details["count"] == 5
    assert issue.details["flag"] is True
    assert issue.details["nothing"] is None


# ---------------------------------------------------------------------------
# IssueSummary
# ---------------------------------------------------------------------------


def test_issue_summary_with_issues(
    sample_opp_context: OpportunityContext,
    sample_issue_stale: Issue,
    sample_issue_critical: Issue,
) -> None:
    summary = IssueSummary(
        opportunity_id="opp-1",
        opportunity_name="Acme Corp Expansion",
        owner_email="alex@demo.com",
        priority="high",
        issues=[sample_issue_critical, sample_issue_stale],
        context=sample_opp_context,
        suggested_action="Call the client.",
        action_rationale="This helps avoid forecast slippage.",
    )
    assert summary.opportunity_id == "opp-1"
    assert len(summary.issues) == 2
    assert summary.suggested_action == "Call the client."
    assert summary.action_rationale == "This helps avoid forecast slippage."


def test_issue_summary_suggested_action_defaults_none(
    sample_opp_context: OpportunityContext,
    sample_issue_stale: Issue,
) -> None:
    summary = IssueSummary(
        opportunity_id="opp-2",
        opportunity_name="Some Deal",
        owner_email="rep@demo.com",
        priority="medium",
        issues=[sample_issue_stale],
        context=sample_opp_context,
    )
    assert summary.suggested_action is None
    assert summary.action_rationale is None


def test_issue_summary_invalid_priority_raises(
    sample_opp_context: OpportunityContext,
    sample_issue_stale: Issue,
) -> None:
    with pytest.raises(ValidationError):
        IssueSummary(
            opportunity_id="opp-3",
            opportunity_name="Bad Priority Deal",
            owner_email="rep@demo.com",
            priority="critical",  # type: ignore[arg-type]
            issues=[sample_issue_stale],
            context=sample_opp_context,
        )


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


def test_brief_create_and_access() -> None:
    brief = Brief(subject="Pipeline Report", body="Here are your top issues...")
    assert brief.subject == "Pipeline Report"
    assert brief.body == "Here are your top issues..."


def test_brief_is_frozen() -> None:
    brief = Brief(subject="Subject", body="Body")
    with pytest.raises(FrozenInstanceError):
        brief.subject = "New Subject"  # type: ignore[misc]
