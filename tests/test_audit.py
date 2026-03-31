from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline_coach.models import Issue, IssueSummary, OpportunityContext
from pipeline_coach.observability.logger import write_audit_record


@pytest.fixture()
def sample_summary() -> IssueSummary:
    ctx = OpportunityContext(
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
    return IssueSummary(
        opportunity_id="opp-1",
        opportunity_name="Acme Corp Expansion",
        owner_email="alex@demo.com",
        priority="high",
        issues=[
            Issue(rule_id="close_date_past", severity="high", message="Close date past"),
            Issue(rule_id="stale_in_stage", severity="medium", message="Stale in stage"),
        ],
        context=ctx,
        suggested_action="Schedule a call with the Acme team.",
        action_rationale="This prevents forecast drift on a high-priority deal.",
    )


def test_write_audit_creates_jsonl(tmp_path: Path, sample_summary: IssueSummary) -> None:
    write_audit_record(
        run_id="run-abc",
        summaries=[sample_summary],
        emails_sent=1,
        emails_failed=0,
        audit_dir=tmp_path,
    )

    audit_file = tmp_path / "audit_log.jsonl"
    assert audit_file.exists()

    lines = audit_file.read_text().strip().splitlines()
    assert len(lines) == 2

    run_record = json.loads(lines[0])
    assert run_record["type"] == "run"
    assert run_record["run_id"] == "run-abc"

    issue_record = json.loads(lines[1])
    assert issue_record["type"] == "issue"
    assert issue_record["opportunity_id"] == "opp-1"


def test_audit_pii_redaction(tmp_path: Path, sample_summary: IssueSummary) -> None:
    write_audit_record(
        run_id="run-redact",
        summaries=[sample_summary],
        emails_sent=1,
        emails_failed=0,
        redact_pii=True,
        audit_dir=tmp_path,
    )

    lines = (tmp_path / "audit_log.jsonl").read_text().strip().splitlines()
    issue_record = json.loads(lines[1])
    assert issue_record["owner_email"] == "[REDACTED]"


def test_audit_record_structure(tmp_path: Path, sample_summary: IssueSummary) -> None:
    write_audit_record(
        run_id="run-struct",
        summaries=[sample_summary],
        emails_sent=2,
        emails_failed=1,
        audit_dir=tmp_path,
    )

    lines = (tmp_path / "audit_log.jsonl").read_text().strip().splitlines()
    run_record = json.loads(lines[0])
    issue_record = json.loads(lines[1])

    for key in (
        "type",
        "run_id",
        "timestamp",
        "opportunities_with_issues",
        "emails_sent",
        "emails_failed",
    ):
        assert key in run_record, f"Missing key in run record: {key}"

    for key in (
        "type",
        "run_id",
        "timestamp",
        "opportunity_id",
        "opportunity_name",
        "owner_email",
        "priority",
        "rule_ids",
        "suggested_action",
        "action_rationale",
    ):
        assert key in issue_record, f"Missing key in issue record: {key}"

    assert run_record["opportunities_with_issues"] == 1
    assert run_record["emails_sent"] == 2
    assert run_record["emails_failed"] == 1
    assert issue_record["rule_ids"] == ["close_date_past", "stale_in_stage"]
    assert "forecast drift" in issue_record["action_rationale"]


def test_audit_handles_write_error(tmp_path: Path, sample_summary: IssueSummary) -> None:
    with patch("builtins.open", side_effect=IOError("disk full")):
        # Must not raise
        write_audit_record(
            run_id="run-err",
            summaries=[sample_summary],
            emails_sent=0,
            emails_failed=1,
            audit_dir=tmp_path,
        )
