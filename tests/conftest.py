from __future__ import annotations

from datetime import date, datetime

import pytest
from pipeline_coach.models import Issue, IssueSummary, OpportunityContext


@pytest.fixture()
def sample_opp_context() -> OpportunityContext:
    return OpportunityContext(
        id="opp-1",
        name="Acme Corp Expansion",
        amount=120_000.0,
        stage="Negotiation",
        owner_email="alex@demo.com",
        owner_name="Alex Doe",
        company_name="Acme Corp",
        close_date=date(2026, 3, 15),
        last_activity_at=datetime(2026, 3, 12, 10, 0),
        days_in_stage=21,
        days_since_last_activity=18,
        has_decision_maker=True,
    )


@pytest.fixture()
def sample_opp_context_clean() -> OpportunityContext:
    return OpportunityContext(
        id="opp-clean",
        name="Brightwave Onboarding",
        amount=50_000.0,
        stage="Discovery",
        owner_email="jordan@demo.com",
        owner_name="Jordan Lee",
        company_name="Brightwave",
        close_date=date(2026, 5, 1),
        last_activity_at=datetime(2026, 3, 28, 14, 0),
        days_in_stage=3,
        days_since_last_activity=2,
        has_decision_maker=True,
    )


@pytest.fixture()
def sample_opp_context_missing_fields() -> OpportunityContext:
    return OpportunityContext(
        id="opp-missing",
        name="NimbusHQ Deal",
        amount=None,
        stage="Proposal",
        owner_email="alex@demo.com",
        owner_name="Alex Doe",
        company_name="NimbusHQ",
        close_date=None,
        last_activity_at=None,
        days_in_stage=30,
        days_since_last_activity=None,
        has_decision_maker=False,
    )


@pytest.fixture()
def sample_issue_stale() -> Issue:
    return Issue(
        rule_id="stale_in_stage",
        severity="medium",
        message="Stale in Negotiation: 21 days (threshold: 7)",
        details={"stage": "Negotiation", "days": 21, "threshold": 7},
    )


@pytest.fixture()
def sample_issue_critical() -> Issue:
    return Issue(
        rule_id="close_date_past",
        severity="high",
        message="Close date 2026-03-15 is in the past",
        details={"close_date": "2026-03-15"},
    )


@pytest.fixture()
def sample_issue_summary(
    sample_opp_context: OpportunityContext,
    sample_issue_stale: Issue,
    sample_issue_critical: Issue,
) -> IssueSummary:
    return IssueSummary(
        opportunity_id="opp-1",
        opportunity_name="Acme Corp Expansion",
        owner_email="alex@demo.com",
        priority="high",
        issues=[sample_issue_critical, sample_issue_stale],
        context=sample_opp_context,
        suggested_action="Schedule a call with the Acme team to confirm the deal timeline.",
    )
