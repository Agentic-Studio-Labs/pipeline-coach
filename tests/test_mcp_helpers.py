from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pipeline_coach.mcp.helpers import (
    build_crm_link,
    fuzzy_match_company,
    fuzzy_match_opportunity,
    generate_mcp_run_id,
    read_audit_runs,
    read_run_issues,
)

from pipeline_coach.models import OpportunityContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_contexts() -> list[OpportunityContext]:
    return [
        OpportunityContext(
            id="opp-1",
            name="Acme Expansion",
            stage="PROPOSAL",
            owner_email="alex@demo.com",
            company_name="Acme Corp",
            amount=120_000.0,
            close_date=date(2026, 4, 15),
        ),
        OpportunityContext(
            id="opp-2",
            name="Acme Renewal",
            stage="MEETING",
            owner_email="alex@demo.com",
            company_name="Acme Corp",
            amount=30_000.0,
        ),
        OpportunityContext(
            id="opp-3",
            name="Northwind Migration",
            stage="PROPOSAL",
            owner_email="jordan@demo.com",
            company_name="Northwind",
            amount=80_000.0,
        ),
    ]


# ---------------------------------------------------------------------------
# fuzzy_match_opportunity
# ---------------------------------------------------------------------------


def test_fuzzy_match_opportunity_exact_id(sample_contexts):
    match, info = fuzzy_match_opportunity("opp-2", sample_contexts)
    assert match is not None
    assert match.id == "opp-2"
    assert info["match_type"] == "uuid"


def test_fuzzy_match_opportunity_exact_name(sample_contexts):
    match, info = fuzzy_match_opportunity("Northwind Migration", sample_contexts)
    assert match is not None
    assert match.id == "opp-3"
    assert info["match_type"] == "exact_name"


def test_fuzzy_match_opportunity_case_insensitive_name(sample_contexts):
    match, info = fuzzy_match_opportunity("northwind migration", sample_contexts)
    assert match is not None
    assert match.id == "opp-3"
    assert info["match_type"] == "exact_name"


def test_fuzzy_match_opportunity_substring(sample_contexts):
    match, info = fuzzy_match_opportunity("Northwind", sample_contexts)
    assert match is not None
    assert match.id == "opp-3"
    assert info["match_type"] == "substring"


def test_fuzzy_match_opportunity_multiple_matches_other_matches_populated(sample_contexts):
    # "Acme" substring matches both opp-1 and opp-2
    match, info = fuzzy_match_opportunity("Acme", sample_contexts)
    assert match is not None
    assert len(info["other_matches"]) >= 1
    # matched_name should be populated
    assert info["matched_name"] is not None


def test_fuzzy_match_opportunity_no_match(sample_contexts):
    match, info = fuzzy_match_opportunity("Zephyr Industries", sample_contexts)
    assert match is None
    assert info["match_type"] == "none"
    assert info["matched_name"] is None


# ---------------------------------------------------------------------------
# fuzzy_match_company
# ---------------------------------------------------------------------------


def test_fuzzy_match_company_exact(sample_contexts):
    matches, info = fuzzy_match_company("Acme Corp", sample_contexts)
    assert len(matches) == 2
    ids = {m.id for m in matches}
    assert ids == {"opp-1", "opp-2"}
    assert info["match_type"] == "exact"


def test_fuzzy_match_company_substring(sample_contexts):
    matches, info = fuzzy_match_company("north", sample_contexts)
    assert len(matches) == 1
    assert matches[0].id == "opp-3"
    assert info["match_type"] == "substring"


def test_fuzzy_match_company_no_match(sample_contexts):
    matches, info = fuzzy_match_company("Unknown Co", sample_contexts)
    assert matches == []
    assert info["match_type"] == "none"


# ---------------------------------------------------------------------------
# build_crm_link
# ---------------------------------------------------------------------------


def test_build_crm_link_with_public_url():
    link = build_crm_link("opp-42", crm_url="https://crm.example.com")
    assert link == "https://crm.example.com/object/opportunity/opp-42"


def test_build_crm_link_strips_trailing_slash():
    link = build_crm_link("opp-42", crm_url="https://crm.example.com/")
    assert link == "https://crm.example.com/object/opportunity/opp-42"


# ---------------------------------------------------------------------------
# read_audit_runs
# ---------------------------------------------------------------------------


def _write_audit_records(audit_dir: Path, records: list[dict]) -> None:
    audit_file = audit_dir / "audit_log.jsonl"
    with audit_file.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def test_read_audit_runs_reads_run_records(tmp_path: Path):
    records = [
        {
            "type": "run",
            "run_id": "mcp-aabbccdd",
            "timestamp": "2026-03-29T08:00:00+00:00",
            "opportunities_with_issues": 3,
            "emails_sent": 2,
            "emails_failed": 0,
            "errors": [],
        },
        {
            "type": "issue",
            "run_id": "mcp-aabbccdd",
            "timestamp": "2026-03-29T08:00:00+00:00",
            "opportunity_id": "opp-1",
            "opportunity_name": "Acme Expansion",
            "owner_email": "alex@demo.com",
            "priority": "high",
            "rule_ids": ["close_date_past"],
        },
    ]
    _write_audit_records(tmp_path, records)

    runs = read_audit_runs(audit_dir=tmp_path)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "mcp-aabbccdd"
    assert runs[0]["type"] == "run"


def test_read_audit_runs_respects_limit(tmp_path: Path):
    records = []
    for i in range(15):
        day = 25 + (i % 5)  # days 25-29
        records.append(
            {
                "type": "run",
                "run_id": f"mcp-{i:08x}",
                "timestamp": f"2026-03-{day:02d}T08:00:00+00:00",
                "opportunities_with_issues": 1,
                "emails_sent": 1,
                "emails_failed": 0,
                "errors": [],
            }
        )
    _write_audit_records(tmp_path, records)

    runs = read_audit_runs(audit_dir=tmp_path, limit=5)
    assert len(runs) == 5


def test_read_audit_runs_missing_file_returns_empty(tmp_path: Path):
    runs = read_audit_runs(audit_dir=tmp_path)
    assert runs == []


# ---------------------------------------------------------------------------
# read_run_issues
# ---------------------------------------------------------------------------


def test_read_run_issues_returns_run_and_issues(tmp_path: Path):
    records = [
        {
            "type": "run",
            "run_id": "mcp-run1",
            "timestamp": "2026-03-28T08:00:00+00:00",
            "opportunities_with_issues": 1,
            "emails_sent": 1,
            "emails_failed": 0,
            "errors": [],
        },
        {
            "type": "issue",
            "run_id": "mcp-run1",
            "timestamp": "2026-03-28T08:00:00+00:00",
            "opportunity_id": "opp-1",
            "opportunity_name": "Acme Expansion",
            "owner_email": "alex@demo.com",
            "priority": "high",
            "rule_ids": ["stale_in_stage"],
        },
        {
            "type": "issue",
            "run_id": "mcp-run1",
            "timestamp": "2026-03-28T08:00:00+00:00",
            "opportunity_id": "opp-3",
            "opportunity_name": "Northwind Migration",
            "owner_email": "jordan@demo.com",
            "priority": "medium",
            "rule_ids": ["missing_close_date"],
        },
    ]
    _write_audit_records(tmp_path, records)

    run_record, issues = read_run_issues(run_id="mcp-run1", audit_dir=tmp_path)
    assert run_record is not None
    assert run_record["run_id"] == "mcp-run1"
    assert len(issues) == 2
    opp_ids = {i["opportunity_id"] for i in issues}
    assert opp_ids == {"opp-1", "opp-3"}


def test_read_run_issues_returns_errors_from_run_record(tmp_path: Path):
    records = [
        {
            "type": "run",
            "run_id": "mcp-errs",
            "timestamp": "2026-03-27T08:00:00+00:00",
            "opportunities_with_issues": 0,
            "emails_sent": 0,
            "emails_failed": 0,
            "errors": ["fetch_companies failed: timeout", "fetch_people failed: timeout"],
        },
    ]
    _write_audit_records(tmp_path, records)

    run_record, issues = read_run_issues(run_id="mcp-errs", audit_dir=tmp_path)
    assert run_record is not None
    assert len(run_record["errors"]) == 2
    assert issues == []


def test_read_run_issues_unknown_run_id_returns_none(tmp_path: Path):
    records = [
        {
            "type": "run",
            "run_id": "mcp-known",
            "timestamp": "2026-03-26T08:00:00+00:00",
            "opportunities_with_issues": 0,
            "emails_sent": 0,
            "emails_failed": 0,
            "errors": [],
        },
    ]
    _write_audit_records(tmp_path, records)

    run_record, issues = read_run_issues(run_id="mcp-unknown", audit_dir=tmp_path)
    assert run_record is None
    assert issues == []


# ---------------------------------------------------------------------------
# generate_mcp_run_id
# ---------------------------------------------------------------------------


def test_generate_mcp_run_id_format():
    run_id = generate_mcp_run_id()
    assert run_id.startswith("mcp-")
    suffix = run_id[4:]
    assert len(suffix) == 8
    assert suffix.isalnum()


def test_generate_mcp_run_id_unique():
    ids = {generate_mcp_run_id() for _ in range(50)}
    assert len(ids) == 50
