from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from pipeline_coach.config import EscalationConfig, RulesConfig, load_rules_config
from pipeline_coach.models import Brief, Issue, IssueSummary, OpportunityContext
from pipeline_coach.workflow.graph import (
    build_graph,
    fetch_companies,
    join_data,
    send_emails,
    should_retry_actions,
    validate_actions,
)

RULES_YAML = """\
excluded_stages:
  - Closed Won
  - Closed Lost

rules:
  stale_in_stage:
    enabled: true
    default_days: 14
    by_stage:
      Negotiation: 7
      Proposal: 10
    severity: medium

  no_recent_activity:
    enabled: true
    days: 7
    severity: medium

  close_date_past:
    enabled: true
    severity: high

  close_date_soon_no_activity:
    enabled: true
    close_date_soon_days: 7
    no_activity_days: 7
    severity: high

  missing_amount:
    enabled: true
    severity: medium

  missing_close_date:
    enabled: true
    severity: medium

  missing_decision_maker:
    enabled: true
    by_stage:
      Proposal: true
      Negotiation: true
    severity: low
"""

TODAY = date(2026, 3, 30)

ESCALATION_CONFIG = EscalationConfig(
    default_manager="vp@demo.com",
    overrides={"alex@demo.com": "mgr-a@demo.com"},
    critical_amount_threshold=50_000.0,
)


def _mock_fetch(collection: str, fields: str) -> list[dict]:
    data: dict[str, list[dict]] = {
        "companies": [{"id": "c1", "name": "Acme Corp"}],
        "people": [
            {
                "id": "p1",
                "name": {"firstName": "Jane", "lastName": "Doe"},
                "emails": {"primaryEmail": "jane@acme.com"},
                "companyId": "c1",
                "jobTitle": "CTO",
            }
        ],
        "opportunities": [
            {
                "id": "opp-1",
                "name": "Acme Expansion",
                "amount": {"amountMicros": 120000000000, "currencyCode": "USD"},
                "stage": "Negotiation",
                "closeDate": "2026-03-15T00:00:00Z",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-03-09T00:00:00Z",
                "stageChangedAt": "2026-03-09T00:00:00Z",
                "companyId": "c1",
                "pointOfContactId": "p1",
                "ownerId": "m1",
            }
        ],
        "tasks": [
            {
                "id": "t1",
                "createdAt": "2026-03-12T10:00:00Z",
                "updatedAt": "2026-03-12T10:00:00Z",
                "status": "DONE",
                "completedAt": "2026-03-12T10:00:00Z",
                "taskTargets": {"edges": [{"node": {"opportunityId": "opp-1"}}]},
            }
        ],
        "workspaceMembers": [
            {
                "id": "m1",
                "name": {"firstName": "Alex", "lastName": "Doe"},
                "userEmail": "alex@demo.com",
            }
        ],
    }
    return data[collection]


@pytest.fixture()
def rules_config(tmp_path) -> RulesConfig:
    config_file = tmp_path / "rules.yaml"
    config_file.write_text(RULES_YAML)
    return load_rules_config(config_file)


@pytest.fixture()
def mock_twenty_client() -> MagicMock:
    client = MagicMock()
    client.fetch_all.side_effect = _mock_fetch
    return client


@pytest.fixture()
def mock_email_client() -> MagicMock:
    client = MagicMock()
    client.send.return_value = "email-id-123"
    return client


def _initial_state() -> dict:
    return {
        "companies": [],
        "people": [],
        "opportunities": [],
        "tasks": [],
        "workspace_members": [],
        "contexts": [],
        "validated_summaries": [],
        "pending_summaries": [],
        "ae_briefs": {},
        "escalation_briefs": {},
        "action_retry_count_by_opp": {},
        "run_id": "test-run",
        "emails_sent": 0,
        "emails_failed": 0,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_full_pipeline_produces_briefs(
    rules_config: RulesConfig,
    mock_twenty_client: MagicMock,
    mock_email_client: MagicMock,
) -> None:
    app = build_graph(
        twenty_client=mock_twenty_client,
        email_client=mock_email_client,
        rules_config=rules_config,
        escalation_config=ESCALATION_CONFIG,
        use_llm=False,
        today=TODAY,
        excluded_stages=["Closed Won", "Closed Lost"],
    )
    result = app.invoke(_initial_state())

    assert len(result["validated_summaries"]) > 0
    assert "alex@demo.com" in result["ae_briefs"]
    brief = result["ae_briefs"]["alex@demo.com"]
    assert isinstance(brief, Brief)
    assert mock_email_client.send.called


def test_critical_deal_triggers_escalation(
    rules_config: RulesConfig,
    mock_twenty_client: MagicMock,
    mock_email_client: MagicMock,
) -> None:
    app = build_graph(
        twenty_client=mock_twenty_client,
        email_client=mock_email_client,
        rules_config=rules_config,
        escalation_config=ESCALATION_CONFIG,
        use_llm=False,
        today=TODAY,
        excluded_stages=["Closed Won", "Closed Lost"],
    )
    result = app.invoke(_initial_state())

    # The deal is $120k, priority high (close_date_past), above $50k threshold
    assert "mgr-a@demo.com" in result["escalation_briefs"]
    brief = result["escalation_briefs"]["mgr-a@demo.com"]
    assert isinstance(brief, Brief)
    assert "Escalation" in brief.subject


# ---------------------------------------------------------------------------
# Node-level unit tests
# ---------------------------------------------------------------------------


def test_fetch_companies_error_handling() -> None:
    client = MagicMock()
    client.fetch_all.side_effect = RuntimeError("connection refused")
    result = fetch_companies(_initial_state(), twenty_client=client)
    assert result["companies"] == []
    assert len(result["errors"]) == 1
    assert "fetch_companies failed" in result["errors"][0]


def test_join_data_produces_contexts() -> None:
    state = _initial_state()
    state["companies"] = [{"id": "c1", "name": "Acme Corp"}]
    state["people"] = [
        {
            "id": "p1",
            "name": {"firstName": "Jane", "lastName": "Doe"},
            "emails": {"primaryEmail": "jane@acme.com"},
            "companyId": "c1",
            "jobTitle": "CTO",
        }
    ]
    state["opportunities"] = [
        {
            "id": "opp-1",
            "name": "Acme Expansion",
            "amount": {"amountMicros": 120000000000, "currencyCode": "USD"},
            "stage": "Negotiation",
            "closeDate": "2026-03-15T00:00:00Z",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-03-09T00:00:00Z",
            "stageChangedAt": "2026-03-09T00:00:00Z",
            "companyId": "c1",
            "pointOfContactId": "p1",
            "ownerId": "m1",
        }
    ]
    state["tasks"] = []
    state["workspace_members"] = [
        {
            "id": "m1",
            "name": {"firstName": "Alex", "lastName": "Doe"},
            "userEmail": "alex@demo.com",
        }
    ]

    result = join_data(state, today=TODAY)
    assert len(result["contexts"]) == 1
    assert result["contexts"][0].id == "opp-1"


def test_should_retry_with_pending() -> None:
    state = _initial_state()
    ctx = OpportunityContext(
        id="opp-1",
        name="Deal",
        stage="Negotiation",
        owner_email="a@b.com",
    )
    state["pending_summaries"] = [
        IssueSummary(
            opportunity_id="opp-1",
            opportunity_name="Deal",
            owner_email="a@b.com",
            priority="high",
            issues=[],
            context=ctx,
        )
    ]
    assert should_retry_actions(state) == "generate_actions"


def test_should_retry_without_pending() -> None:
    state = _initial_state()
    state["pending_summaries"] = []
    assert should_retry_actions(state) == "route_by_severity"


def test_validate_actions_moves_valid_to_validated() -> None:
    ctx = OpportunityContext(
        id="opp-1",
        name="Deal",
        stage="Negotiation",
        owner_email="a@b.com",
    )
    issue = Issue(rule_id="close_date_past", severity="high", message="Close date is in the past")
    summary = IssueSummary(
        opportunity_id="opp-1",
        opportunity_name="Deal",
        owner_email="a@b.com",
        priority="high",
        issues=[issue],
        context=ctx,
        suggested_action="Update the close date to next quarter.",
    )
    state = _initial_state()
    state["pending_summaries"] = [summary]

    result = validate_actions(state, use_llm=False)
    assert len(result["validated_summaries"]) == 1
    assert result["validated_summaries"][0].opportunity_id == "opp-1"
    assert len(result["pending_summaries"]) == 0


def test_send_emails_counts_correctly() -> None:
    client = MagicMock()
    client.send.return_value = "email-id-ok"

    brief_a = Brief(subject="Brief A", body="Body A")
    brief_b = Brief(subject="Brief B", body="Body B")

    state = _initial_state()
    state["ae_briefs"] = {"user1@test.com": brief_a, "user2@test.com": brief_b}
    state["escalation_briefs"] = {}

    result = send_emails(state, email_client=client)
    assert result["emails_sent"] == 2
    assert result["emails_failed"] == 0
    assert client.send.call_count == 2
