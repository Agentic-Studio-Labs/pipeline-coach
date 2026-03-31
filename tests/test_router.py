from __future__ import annotations

import pytest
from pipeline_coach.delivery.router import route_summaries

from pipeline_coach.config import EscalationConfig
from pipeline_coach.models import Issue, IssueSummary, OpportunityContext


@pytest.fixture()
def escalation_config() -> EscalationConfig:
    return EscalationConfig(
        default_manager="vp@demo.com",
        overrides={"alex@demo.com": "mgr-a@demo.com"},
        critical_amount_threshold=50_000.0,
    )


def _make_summary(
    owner_email: str,
    priority: str,
    amount: float | None,
    opp_id: str = "opp-1",
) -> IssueSummary:
    context = OpportunityContext(
        id=opp_id,
        name=f"Deal {opp_id}",
        amount=amount,
        stage="Negotiation",
        owner_email=owner_email,
    )
    issue = Issue(rule_id="close_date_past", severity=priority, message="msg")
    return IssueSummary(
        opportunity_id=opp_id,
        opportunity_name=f"Deal {opp_id}",
        owner_email=owner_email,
        priority=priority,
        issues=[issue],
        context=context,
    )


def test_critical_deal_generates_escalation(escalation_config: EscalationConfig) -> None:
    summary = _make_summary("alex@demo.com", "high", 75_000.0)
    result = route_summaries([summary], escalation_config)

    assert "alex@demo.com" in result.ae_briefs
    assert result.ae_briefs["alex@demo.com"] == [summary]
    assert "mgr-a@demo.com" in result.escalations
    assert result.escalations["mgr-a@demo.com"] == [summary]


def test_non_critical_medium_priority_no_escalation(escalation_config: EscalationConfig) -> None:
    summary = _make_summary("alex@demo.com", "medium", 100_000.0)
    result = route_summaries([summary], escalation_config)

    assert "alex@demo.com" in result.ae_briefs
    assert result.escalations == {}


def test_unknown_ae_uses_default_manager(escalation_config: EscalationConfig) -> None:
    summary = _make_summary("newbie@demo.com", "high", 60_000.0)
    result = route_summaries([summary], escalation_config)

    assert "newbie@demo.com" in result.ae_briefs
    assert "vp@demo.com" in result.escalations
    assert result.escalations["vp@demo.com"] == [summary]


def test_high_priority_low_amount_no_escalation(escalation_config: EscalationConfig) -> None:
    summary = _make_summary("alex@demo.com", "high", 5_000.0)
    result = route_summaries([summary], escalation_config)

    assert "alex@demo.com" in result.ae_briefs
    assert result.escalations == {}


def test_multiple_aes_grouped_correctly(escalation_config: EscalationConfig) -> None:
    s1 = _make_summary("alex@demo.com", "high", 60_000.0, opp_id="opp-1")
    s2 = _make_summary("alex@demo.com", "medium", 10_000.0, opp_id="opp-2")
    s3 = _make_summary("jordan@demo.com", "high", 80_000.0, opp_id="opp-3")

    result = route_summaries([s1, s2, s3], escalation_config)

    assert set(result.ae_briefs.keys()) == {"alex@demo.com", "jordan@demo.com"}
    assert len(result.ae_briefs["alex@demo.com"]) == 2
    assert len(result.ae_briefs["jordan@demo.com"]) == 1

    # alex's critical deal escalates to mgr-a, jordan's to vp (default)
    assert "mgr-a@demo.com" in result.escalations
    assert result.escalations["mgr-a@demo.com"] == [s1]
    assert "vp@demo.com" in result.escalations
    assert result.escalations["vp@demo.com"] == [s3]
