"""Seed a Twenty CRM instance with sample pipeline data for Pipeline Coach demos."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline_coach.ingestion.twenty_client import TwentyClient  # noqa: E402

# Rate limit: Twenty allows 100 requests per 60s. Space mutations apart.
_MUTATION_DELAY = 0.7


def _mutate(client: TwentyClient, query: str) -> dict:
    """Execute a mutation with rate limit pacing."""
    time.sleep(_MUTATION_DELAY)
    return client._query(query)


OPP_OBJECT_METADATA_QUERY = """{
    objects(paging: {first: 100}) {
        edges { node { id nameSingular fields(paging: {first: 200}) {
            edges { node { name } }
        } } }
    }
}"""

CREATE_FIELD_MUTATION = """mutation CreateField($input: CreateOneFieldMetadataInput!) {
    createOneField(input: $input) { id name }
}"""


def ensure_stage_changed_at_field(client: TwentyClient) -> None:
    """Create stageChangedAt custom field on Opportunity if it doesn't exist."""
    # Query metadata to find the Opportunity object and its fields
    result = client._http.post(
        client._graphql_url.replace("/graphql", "/metadata"),
        json={"query": OPP_OBJECT_METADATA_QUERY},
        headers=dict(client._http.headers),
    )
    data = result.json()["data"]

    opp_obj = None
    for edge in data["objects"]["edges"]:
        if edge["node"]["nameSingular"] == "opportunity":
            opp_obj = edge["node"]
            break

    if opp_obj is None:
        print("  WARNING: Opportunity object not found in metadata, skipping custom field")
        return

    # Check if stageChangedAt already exists
    existing_fields = {f["node"]["name"] for f in opp_obj["fields"]["edges"]}
    if "stageChangedAt" in existing_fields:
        print("  stageChangedAt field already exists")
        return

    # Create the custom field
    resp = client._http.post(
        client._graphql_url.replace("/graphql", "/metadata"),
        json={
            "query": CREATE_FIELD_MUTATION,
            "variables": {
                "input": {
                    "field": {
                        "objectMetadataId": opp_obj["id"],
                        "name": "stageChangedAt",
                        "label": "Stage Changed At",
                        "type": "DATE_TIME",
                        "description": "Last stage change timestamp (used by Pipeline Coach)",
                    }
                }
            },
        },
        headers=dict(client._http.headers),
    )
    resp_data = resp.json()
    if "errors" in resp_data:
        print(f"  WARNING: Failed to create stageChangedAt: {resp_data['errors']}")
    else:
        print(f"  created stageChangedAt field ({resp_data['data']['createOneField']['id']})")


COMPANIES = ["Acme Corp", "Northwind", "GlobalSoft", "Brightwave", "NimbusHQ"]

CONTACTS = [
    ("Jane", "Smith", "jane@acme.com", 0),
    ("Bob", "Jones", "bob@northwind.com", 1),
    ("Alice", "Chen", "alice@globalsoft.com", 2),
    ("Marco", "Rivera", "marco@brightwave.com", 3),
    ("Sara", "Kim", "sara@nimbushq.com", 4),
    ("Tom", "Walsh", "tom@acme.com", 0),
    ("Diana", "Park", "diana@northwind.com", 1),
    ("Liam", "Foster", "liam@globalsoft.com", 2),
    ("Nina", "Okafor", "nina@brightwave.com", 3),
    ("Carlos", "Reyes", "carlos@nimbushq.com", 4),
]

_now = datetime.now(timezone.utc)


def _days_ago(n: int) -> str:
    return (_now - timedelta(days=n)).strftime("%Y-%m-%d")


def _days_from_now(n: int) -> str:
    return (_now + timedelta(days=n)).strftime("%Y-%m-%d")


def _iso_days_ago(n: int) -> str:
    """Return full ISO 8601 timestamp for stageChangedAt."""
    return (_now - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


# Opportunities: (name, stage, amount_micros, close_date, co_idx, ct_idx, stage_changed_days_ago)
# Hygiene issues baked in:
#   - Some have no amount (None)
#   - Some have past close dates (stale)
#   - Some close within 7 days with no recent stage change (stuck)
#   - Closed Won/Lost for variety
OPPORTUNITIES = [
    # 0: healthy deal
    ("Acme Platform Upgrade", "MEETING", 45_000_000_000, _days_from_now(30), 0, 0, 5),
    # 1: stale — close date in the past
    ("Northwind Analytics", "PROPOSAL", 120_000_000_000, _days_ago(15), 1, 1, 45),
    # 2: closing soon, stuck in stage for >14 days
    ("GlobalSoft Security Suite", "PROPOSAL", 80_000_000_000, _days_from_now(5), 2, 2, 21),
    # 3: missing amount
    ("Brightwave Data Migration", "MEETING", None, _days_from_now(45), 3, 3, 3),
    # 4: missing close date (None)
    ("NimbusHQ Integration", "CUSTOMER", 200_000_000_000, None, 4, 4, 7),
    # 5: stale + missing amount
    ("Acme Support Contract", "PROPOSAL", None, _days_ago(30), 0, 5, 60),
    # 6: closing in 4 days, no stage movement in 20 days
    ("Northwind CRM Rollout", "MEETING", 55_000_000_000, _days_from_now(4), 1, 6, 20),
    # 7: Won deal (terminal stage)
    ("GlobalSoft ERP Deal", "CUSTOMER", 300_000_000_000, _days_ago(10), 2, 7, 12),
    # 8: Another customer deal
    ("Brightwave Consulting", "CUSTOMER", 25_000_000_000, _days_ago(5), 3, 8, 8),
    # 9: healthy, near close
    ("NimbusHQ Cloud Migration", "CUSTOMER", 150_000_000_000, _days_from_now(14), 4, 9, 2),
    # 10: no amount, past close date
    ("Acme Expansion License", "MEETING", None, _days_ago(7), 0, 0, 35),
    # 11: very stale
    ("Northwind Legacy Support", "PROPOSAL", 18_000_000_000, _days_ago(60), 1, 1, 90),
    # 12: closing tomorrow, high value, stuck
    ("GlobalSoft Platform Deal", "PROPOSAL", 500_000_000_000, _days_from_now(1), 2, 2, 30),
    # 13: missing close date + missing amount
    ("Brightwave Analytics POC", "MEETING", None, None, 3, 3, 10),
    # 14: healthy
    ("NimbusHQ Security Audit", "CUSTOMER", 75_000_000_000, _days_from_now(60), 4, 4, 1),
]

# (title, status, opportunity_index) — links task to an opportunity via taskTarget
TASKS = [
    ("Follow up with Jane Smith", "TODO", 0),  # Acme Platform Upgrade
    ("Send proposal to Northwind", "TODO", 1),  # Northwind Analytics
    ("Schedule demo for GlobalSoft", "TODO", 2),  # GlobalSoft Security Suite
    ("Review contract for Brightwave", "DONE", 3),  # Brightwave Data Migration
    ("Update Acme opportunity notes", "DONE", 0),  # Acme Platform Upgrade
    ("Call Carlos about NimbusHQ deal", "TODO", 9),  # NimbusHQ Cloud Migration
    ("Send pricing sheet to Liam Foster", "TODO", 6),  # Northwind CRM Rollout
    ("Close out lost Brightwave deal", "DONE", 8),  # Brightwave Consulting
]


def create_companies(client: TwentyClient) -> list[str]:
    ids = []
    for name in COMPANIES:
        result = _mutate(
            client, f'mutation {{ createCompany(data: {{ name: "{name}" }}) {{ id }} }}'
        )
        company_id = result["data"]["createCompany"]["id"]
        ids.append(company_id)
        print(f"  created company: {name} ({company_id})")
    return ids


def create_contacts(client: TwentyClient, company_ids: list[str]) -> list[str]:
    ids = []
    for first, last, email, company_idx in CONTACTS:
        company_id = company_ids[company_idx]
        result = _mutate(
            client,
            f"""mutation {{
                createPerson(data: {{
                    name: {{ firstName: "{first}", lastName: "{last}" }},
                    emails: {{ primaryEmail: "{email}" }},
                    companyId: "{company_id}"
                }}) {{ id }}
            }}""",
        )
        person_id = result["data"]["createPerson"]["id"]
        ids.append(person_id)
        print(f"  created contact: {first} {last} ({person_id})")
    return ids


def create_opportunities(
    client: TwentyClient,
    company_ids: list[str],
    contact_ids: list[str],
    owner_id: str | None = None,
) -> list[str]:
    ids = []
    for (
        name,
        stage,
        amount_micros,
        close_date,
        co_idx,
        ct_idx,
        stage_changed_days_ago,
    ) in OPPORTUNITIES:
        company_id = company_ids[co_idx]
        contact_id = contact_ids[ct_idx]
        stage_changed_at = _iso_days_ago(stage_changed_days_ago)

        # Build optional fields
        amount_field = (
            f'amount: {{ amountMicros: {amount_micros}, currencyCode: "USD" }}, '
            if amount_micros is not None
            else ""
        )
        close_date_field = f'closeDate: "{close_date}", ' if close_date is not None else ""

        result = _mutate(
            client,
            f"""mutation {{
                createOpportunity(data: {{
                    name: "{name}",
                    stage: {stage},
                    {amount_field}{close_date_field}companyId: "{company_id}",
                    pointOfContactId: "{contact_id}"{f', ownerId: "{owner_id}"' if owner_id else ""}
                }}) {{ id }}
            }}""",
        )
        opp_id = result["data"]["createOpportunity"]["id"]
        ids.append(opp_id)

        # Set stageChangedAt via update (custom field can't be set on create)
        _mutate(
            client,
            f"""mutation {{
                updateOpportunity(id: "{opp_id}", data: {{
                    stageChangedAt: "{stage_changed_at}"
                }}) {{ id }}
            }}""",
        )
        print(
            f"  created opportunity: {name} [{stage}] stageChanged={stage_changed_days_ago}d ago ({opp_id})"
        )
    return ids


def create_tasks(client: TwentyClient, opportunity_ids: list[str]) -> list[str]:
    ids = []
    for title, status, opp_idx in TASKS:
        result = _mutate(
            client,
            f"""mutation {{
                createTask(data: {{
                    title: "{title}",
                    status: {status}
                }}) {{ id }}
            }}""",
        )
        task_id = result["data"]["createTask"]["id"]
        ids.append(task_id)

        # Link task to opportunity via taskTarget
        opp_id = opportunity_ids[opp_idx]
        _mutate(
            client,
            f"""mutation {{
                createTaskTarget(data: {{
                    taskId: "{task_id}",
                    targetOpportunityId: "{opp_id}"
                }}) {{ id }}
            }}""",
        )
        print(f"  created task: {title} → {opp_id[:8]}... ({task_id})")
    return ids


def delete_seeded_data(client: TwentyClient, output_path: Path) -> None:
    if not output_path.exists():
        print("No seed_output.json found — nothing to clean.")
        return

    with output_path.open() as f:
        data = json.load(f)

    # Delete in reverse dependency order: tasks → opportunities → contacts → companies
    for task_id in data.get("task_ids", []):
        _mutate(client, f'mutation {{ deleteTask(id: "{task_id}") {{ id }} }}')
        print(f"  deleted task {task_id}")

    for opp_id in data.get("opportunity_ids", []):
        _mutate(client, f'mutation {{ deleteOpportunity(id: "{opp_id}") {{ id }} }}')
        print(f"  deleted opportunity {opp_id}")

    for person_id in data.get("contact_ids", []):
        _mutate(client, f'mutation {{ deletePerson(id: "{person_id}") {{ id }} }}')
        print(f"  deleted contact {person_id}")

    for company_id in data.get("company_ids", []):
        _mutate(client, f'mutation {{ deleteCompany(id: "{company_id}") {{ id }} }}')
        print(f"  deleted company {company_id}")

    print("Clean complete.")


def nuke_all_data(client: TwentyClient) -> None:
    """Delete ALL data from the CRM — tasks, opportunities, people, companies."""
    for collection, mutation in [
        ("tasks", "destroyTask"),
        ("opportunities", "destroyOpportunity"),
        ("people", "destroyPerson"),
        ("companies", "destroyCompany"),
    ]:
        data = client.fetch_all(collection, "id")
        for node in data:
            try:
                _mutate(client, f'mutation {{ {mutation}(id: "{node["id"]}") {{ id }} }}')
            except Exception:
                pass  # some records may have dependencies, skip
        print(f"  deleted {len(data)} {collection}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Twenty CRM with demo pipeline data.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing seeded data (from seed_output.json) before creating new data.",
    )
    parser.add_argument(
        "--nuke",
        action="store_true",
        help="Delete ALL CRM data (not just seeded) before creating new data.",
    )
    args = parser.parse_args()

    api_url = os.environ.get("TWENTY_API_URL")
    api_key = os.environ.get("TWENTY_API_KEY")
    if not api_url or not api_key:
        sys.exit("Error: TWENTY_API_URL and TWENTY_API_KEY must be set in .env or environment.")

    output_path = Path(__file__).resolve().parent / "seed_output.json"

    client = TwentyClient(base_url=api_url, api_key=api_key)

    try:
        if args.nuke:
            print("--- Nuking ALL CRM data ---")
            nuke_all_data(client)
        elif args.clean:
            print("--- Cleaning existing seed data ---")
            delete_seeded_data(client, output_path)

        print("\n--- Ensuring stageChangedAt custom field ---")
        ensure_stage_changed_at_field(client)

        # Get first workspace member as deal owner
        print("\n--- Finding workspace member for deal ownership ---")
        members = client.fetch_all("workspaceMembers", "id name { firstName lastName } userEmail")
        if members:
            owner_id = members[0]["id"]
            print(f"  owner: {members[0].get('userEmail', 'unknown')} ({owner_id})")
        else:
            owner_id = None
            print("  WARNING: no workspace members found, deals will have no owner")

        print("\n--- Creating companies ---")
        company_ids = create_companies(client)

        print("\n--- Creating contacts ---")
        contact_ids = create_contacts(client, company_ids)

        print("\n--- Creating opportunities ---")
        opportunity_ids = create_opportunities(client, company_ids, contact_ids, owner_id=owner_id)

        print("\n--- Creating tasks ---")
        task_ids = create_tasks(client, opportunity_ids)

    finally:
        client.close()

    output = {
        "created_at": _now.isoformat(),
        "company_ids": company_ids,
        "contact_ids": contact_ids,
        "opportunity_ids": opportunity_ids,
        "task_ids": task_ids,
    }
    with output_path.open("w") as f:
        json.dump(output, f, indent=2)

    print("\n--- Summary ---")
    print(f"  Companies:     {len(company_ids)}")
    print(f"  Contacts:      {len(contact_ids)}")
    print(f"  Opportunities: {len(opportunity_ids)}")
    print(f"  Tasks:         {len(task_ids)}")
    print(f"\nIDs saved to: {output_path}")


if __name__ == "__main__":
    main()
