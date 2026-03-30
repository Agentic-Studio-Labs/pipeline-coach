from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pipeline_coach.ingestion.normalizer import normalize_opportunities

# ---------------------------------------------------------------------------
# Fixtures — raw GraphQL response shapes
# ---------------------------------------------------------------------------


@pytest.fixture()
def raw_companies() -> list[dict]:
    return [
        {"id": "company-1", "name": "Acme Corp"},
        {"id": "company-2", "name": "Brightwave"},
    ]


@pytest.fixture()
def raw_people() -> list[dict]:
    return [
        {"id": "person-1", "firstName": "Dana", "lastName": "Kim"},
    ]


@pytest.fixture()
def raw_workspace_members() -> list[dict]:
    return [
        {
            "id": "member-1",
            "name": {"firstName": "Alice", "lastName": "Smith"},
            "userEmail": "alice@demo.com",
        },
        {
            "id": "member-2",
            "name": {"firstName": "Bob", "lastName": "Jones"},
            "userEmail": "bob@demo.com",
        },
    ]


@pytest.fixture()
def raw_tasks() -> list[dict]:
    return [
        {
            "id": "task-1",
            "completedAt": "2026-03-25T12:00:00Z",
            "taskTargets": {
                "edges": [
                    {"node": {"opportunityId": "opp-1"}},
                ]
            },
        }
    ]


@pytest.fixture()
def raw_opportunities() -> list[dict]:
    return [
        {
            "id": "opp-1",
            "name": "Acme Expansion",
            "stage": "Negotiation",
            "ownerId": "member-1",
            "companyId": "company-1",
            "pointOfContactId": "person-1",
            "amount": {"amountMicros": "120000000000", "currencyCode": "USD"},
            "closeDate": "2026-06-30",
            "updatedAt": "2026-03-09T00:00:00Z",
            "stageChangedAt": None,
        },
        {
            "id": "opp-2",
            "name": "Brightwave Onboarding",
            "stage": "Discovery",
            "ownerId": "member-2",
            "companyId": "company-2",
            "pointOfContactId": None,
            "amount": None,
            "closeDate": None,
            "updatedAt": "2026-03-09T00:00:00Z",
            "stageChangedAt": None,
        },
    ]


TODAY = date(2026, 3, 30)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basic_normalization_returns_correct_count(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    assert len(result) == 2


def test_amount_conversion_from_micros(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp1 = next(o for o in result if o.id == "opp-1")
    assert opp1.amount == 120_000.0


def test_null_amount_stays_none(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp2 = next(o for o in result if o.id == "opp-2")
    assert opp2.amount is None


def test_owner_mapped_from_workspace_member(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp1 = next(o for o in result if o.id == "opp-1")
    assert opp1.owner_email == "alice@demo.com"
    assert opp1.owner_name == "Alice Smith"


def test_company_name_resolved(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp1 = next(o for o in result if o.id == "opp-1")
    assert opp1.company_name == "Acme Corp"


def test_days_in_stage_from_updated_at(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    # updatedAt = 2026-03-09, today = 2026-03-30 → 21 days
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp1 = next(o for o in result if o.id == "opp-1")
    assert opp1.days_in_stage == 21


def test_last_activity_at_from_tasks(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp1 = next(o for o in result if o.id == "opp-1")
    assert opp1.last_activity_at == datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)


def test_no_tasks_gives_none_activity(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp2 = next(o for o in result if o.id == "opp-2")
    assert opp2.last_activity_at is None


def test_has_decision_maker_true(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp1 = next(o for o in result if o.id == "opp-1")
    assert opp1.has_decision_maker is True


def test_has_decision_maker_false(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    result = normalize_opportunities(
        opportunities=raw_opportunities,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    opp2 = next(o for o in result if o.id == "opp-2")
    assert opp2.has_decision_maker is False


def test_missing_workspace_member_uses_unknown_email(
    raw_opportunities: list[dict],
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    opps = [
        {
            "id": "opp-orphan",
            "name": "Orphan Deal",
            "stage": "Discovery",
            "ownerId": "member-999",  # not in workspace_members
            "companyId": None,
            "pointOfContactId": None,
            "amount": None,
            "closeDate": None,
            "updatedAt": "2026-03-09T00:00:00Z",
            "stageChangedAt": None,
        }
    ]
    result = normalize_opportunities(
        opportunities=opps,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
    )
    assert len(result) == 1
    assert result[0].owner_email == "unknown@unknown.com"


def test_excluded_stages_filter(
    raw_companies: list[dict],
    raw_people: list[dict],
    raw_workspace_members: list[dict],
    raw_tasks: list[dict],
) -> None:
    opps = [
        {
            "id": "opp-closed",
            "name": "Closed Deal",
            "stage": "Closed Won",
            "ownerId": "member-1",
            "companyId": "company-1",
            "pointOfContactId": None,
            "amount": None,
            "closeDate": None,
            "updatedAt": "2026-03-09T00:00:00Z",
            "stageChangedAt": None,
        },
        {
            "id": "opp-open",
            "name": "Open Deal",
            "stage": "Discovery",
            "ownerId": "member-1",
            "companyId": "company-1",
            "pointOfContactId": None,
            "amount": None,
            "closeDate": None,
            "updatedAt": "2026-03-09T00:00:00Z",
            "stageChangedAt": None,
        },
    ]
    result = normalize_opportunities(
        opportunities=opps,
        companies=raw_companies,
        people=raw_people,
        workspace_members=raw_workspace_members,
        tasks=raw_tasks,
        today=TODAY,
        excluded_stages=["Closed Won"],
    )
    assert len(result) == 1
    assert result[0].id == "opp-open"
