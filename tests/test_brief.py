from __future__ import annotations

from datetime import date, datetime

import pytest

from pipeline_coach.coach.brief import (
    _format_amount,
    _format_date,
    render_ae_brief,
    render_escalation_brief,
)
from pipeline_coach.models import Brief, Issue, IssueSummary, OpportunityContext


@pytest.fixture()
def summaries() -> list[IssueSummary]:
    ctx1 = OpportunityContext(
        id="opp-1",
        name="Acme Corp Expansion",
        amount=120_000.0,
        stage="Negotiation",
        owner_email="alex@demo.com",
        owner_name="Alex",
        company_name="Acme Corp",
        close_date=date(2026, 3, 15),
        last_activity_at=datetime(2026, 3, 12, 10, 0),
        days_in_stage=21,
        days_since_last_activity=18,
        has_decision_maker=True,
    )
    ctx2 = OpportunityContext(
        id="opp-2",
        name="Globex Renewal",
        amount=75_000.0,
        stage="Proposal",
        owner_email="alex@demo.com",
        owner_name="Alex",
        company_name="Globex",
        close_date=date(2026, 4, 30),
        last_activity_at=datetime(2026, 3, 20, 9, 0),
        days_in_stage=10,
        days_since_last_activity=10,
        has_decision_maker=False,
    )
    s1 = IssueSummary(
        opportunity_id="opp-1",
        opportunity_name="Acme Corp Expansion",
        owner_email="alex@demo.com",
        priority="high",
        issues=[
            Issue(
                rule_id="close_date_past",
                severity="high",
                message="Close date 2026-03-15 is in the past",
                details={"close_date": "2026-03-15"},
            )
        ],
        context=ctx1,
        suggested_action="Schedule a call with the Acme team to confirm the deal timeline.",
        action_rationale="This prevents forecast drift on a high-priority deal.",
    )
    s2 = IssueSummary(
        opportunity_id="opp-2",
        opportunity_name="Globex Renewal",
        owner_email="alex@demo.com",
        priority="medium",
        issues=[
            Issue(
                rule_id="missing_decision_maker",
                severity="medium",
                message="No decision maker contact on record",
                details={},
            )
        ],
        context=ctx2,
        suggested_action="Identify and add a decision maker for Globex.",
        action_rationale="Without decision maker access, the opportunity can stall.",
    )
    return [s1, s2]


TODAY = date(2026, 3, 30)


class TestFormatHelpers:
    def test_format_amount_with_value(self) -> None:
        assert _format_amount(120_000.0) == "$120,000"

    def test_format_amount_none(self) -> None:
        assert _format_amount(None) == "Not set"

    def test_format_date_future(self) -> None:
        result = _format_date(date(2026, 4, 30), TODAY)
        assert result == "2026-04-30"
        assert "(PAST)" not in result

    def test_format_date_past(self) -> None:
        result = _format_date(date(2026, 3, 15), TODAY)
        assert "(PAST)" in result

    def test_format_date_none(self) -> None:
        assert _format_date(None, TODAY) == "Not set"


class TestRenderAeBrief:
    def test_returns_brief_instance(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert isinstance(result, Brief)

    def test_subject_contains_date(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert str(TODAY) in result.subject

    def test_body_contains_greeting(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "Hi Alex" in result.body

    def test_body_greeting_none_owner(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief(None, summaries, today=TODAY)
        assert result.body.startswith("Hi,")

    def test_body_contains_opp_names(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "Acme Corp Expansion" in result.body
        assert "Globex Renewal" in result.body

    def test_body_contains_issue_messages(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "Close date 2026-03-15 is in the past" in result.body
        assert "No decision maker contact on record" in result.body

    def test_body_contains_suggested_action(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "Schedule a call with the Acme team" in result.body

    def test_body_contains_action_rationale(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "Why now:" in result.body
        assert "forecast drift" in result.body

    def test_body_contains_formatted_amount(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "$120,000" in result.body

    def test_body_signed_pipeline_coach(self, summaries: list[IssueSummary]) -> None:
        result = render_ae_brief("Alex", summaries, today=TODAY)
        assert "Pipeline Coach" in result.body

    def test_empty_summaries(self) -> None:
        result = render_ae_brief("Alex", [], today=TODAY)
        assert isinstance(result, Brief)
        assert str(TODAY) in result.subject


class TestRenderEscalationBrief:
    def test_returns_brief_instance(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert isinstance(result, Brief)

    def test_subject_contains_escalation_tag(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "[Escalation]" in result.subject

    def test_subject_contains_count_and_date(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "2" in result.subject
        assert str(TODAY) in result.subject

    def test_body_contains_ae_name_and_email(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "Alex" in result.body
        assert "alex@demo.com" in result.body

    def test_body_contains_deal_names(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "Acme Corp Expansion" in result.body
        assert "Globex Renewal" in result.body

    def test_body_contains_issue_messages(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "Close date 2026-03-15 is in the past" in result.body

    def test_body_greeting_with_manager(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "Hi Dana" in result.body

    def test_body_greeting_none_manager(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name=None,
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert result.body.startswith("Hi,")

    def test_body_signed_pipeline_coach(self, summaries: list[IssueSummary]) -> None:
        result = render_escalation_brief(
            manager_name="Dana",
            ae_name="Alex",
            ae_email="alex@demo.com",
            summaries=summaries,
            today=TODAY,
        )
        assert "Pipeline Coach" in result.body
