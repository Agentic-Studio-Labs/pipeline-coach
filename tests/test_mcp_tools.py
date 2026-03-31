from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pipeline_coach.mcp.tools import (
    handle_analyze_pipeline,
    handle_get_audit_history,
    handle_get_company_overview,
    handle_get_deal_issues,
    handle_get_deal_overview,
    handle_get_rules_config,
    handle_get_run_details,
    handle_list_stale_deals,
)

from pipeline_coach.config import (
    RulesConfig,
)
from pipeline_coach.models import OpportunityContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CRM_URL = "https://crm.example.com"
TODAY = date(2026, 3, 30)


@pytest.fixture()
def sample_contexts() -> list[OpportunityContext]:
    return [
        OpportunityContext(
            id="opp-1",
            name="Acme Expansion",
            stage="PROPOSAL",
            owner_email="alex@demo.com",
            owner_name="Alex Doe",
            company_name="Acme Corp",
            amount=120_000.0,
            close_date=date(2026, 3, 15),
            days_in_stage=21,
            days_since_last_activity=18,
            has_decision_maker=True,
        ),
        OpportunityContext(
            id="opp-2",
            name="Brightwave Onboarding",
            stage="MEETING",
            owner_email="jordan@demo.com",
            owner_name="Jordan Lee",
            company_name="Brightwave",
            amount=50_000.0,
            close_date=date(2026, 5, 1),
            days_in_stage=3,
            days_since_last_activity=2,
            has_decision_maker=True,
        ),
    ]


@pytest.fixture()
def rules_config(tmp_path: Path) -> RulesConfig:
    rules_yaml = {
        "excluded_stages": ["CUSTOMER"],
        "rules": {
            "stale_in_stage": {
                "enabled": True,
                "default_days": 14,
                "by_stage": {"SCREENING": 21, "PROPOSAL": 7},
                "severity": "medium",
            },
            "no_recent_activity": {
                "enabled": True,
                "days": 7,
                "severity": "medium",
            },
            "close_date_past": {
                "enabled": True,
                "severity": "high",
            },
            "close_date_soon_no_activity": {
                "enabled": True,
                "close_date_soon_days": 7,
                "no_activity_days": 7,
                "severity": "high",
            },
            "missing_amount": {
                "enabled": True,
                "severity": "medium",
            },
            "missing_close_date": {
                "enabled": True,
                "severity": "medium",
            },
            "missing_decision_maker": {
                "enabled": True,
                "by_stage": {"PROPOSAL": True},
                "severity": "low",
            },
        },
    }
    yaml_path = tmp_path / "rules.yaml"
    yaml_path.write_text(yaml.dump(rules_yaml))

    from pipeline_coach.config import load_rules_config

    return load_rules_config(yaml_path)


@pytest.fixture()
def rules_yaml_path(tmp_path: Path) -> Path:
    rules_yaml = {
        "excluded_stages": ["CUSTOMER"],
        "rules": {
            "stale_in_stage": {
                "enabled": True,
                "default_days": 14,
                "by_stage": {"SCREENING": 21, "PROPOSAL": 7},
                "severity": "medium",
            },
            "no_recent_activity": {
                "enabled": True,
                "days": 7,
                "severity": "medium",
            },
            "close_date_past": {
                "enabled": True,
                "severity": "high",
            },
            "close_date_soon_no_activity": {
                "enabled": True,
                "close_date_soon_days": 7,
                "no_activity_days": 7,
                "severity": "high",
            },
            "missing_amount": {
                "enabled": True,
                "severity": "medium",
            },
            "missing_close_date": {
                "enabled": True,
                "severity": "medium",
            },
            "missing_decision_maker": {
                "enabled": True,
                "by_stage": {"PROPOSAL": True},
                "severity": "low",
            },
        },
    }
    yaml_path = tmp_path / "rules.yaml"
    yaml_path.write_text(yaml.dump(rules_yaml))
    return yaml_path


def _write_audit_records(audit_dir: Path, records: list[dict]) -> None:
    audit_file = audit_dir / "audit_log.jsonl"
    with audit_file.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# handle_analyze_pipeline
# ---------------------------------------------------------------------------


class TestAnalyzePipeline:
    def test_returns_structured_result_with_run_id(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_analyze_pipeline(
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["run_id"].startswith("mcp-")
        assert "summaries" in result
        assert "total_opportunities" in result
        assert result["total_opportunities"] == 2

    def test_issues_found_at_least_one(self, sample_contexts, rules_config):
        # opp-1 has close_date in the past and is stale
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_analyze_pipeline(
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["issues_found"] >= 1

    def test_summaries_contain_crm_link(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_analyze_pipeline(
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        for summary in result["summaries"]:
            assert "crm_link" in summary
            assert summary["crm_link"].startswith(CRM_URL)

    def test_clean_deals_return_zero_issues(self, rules_config):
        clean_contexts = [
            OpportunityContext(
                id="opp-clean",
                name="Clean Deal",
                stage="MEETING",
                owner_email="jordan@demo.com",
                owner_name="Jordan Lee",
                company_name="CleanCo",
                amount=50_000.0,
                close_date=date(2026, 5, 1),
                days_in_stage=3,
                days_since_last_activity=2,
                has_decision_maker=True,
            ),
        ]
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=clean_contexts,
        ):
            result = handle_analyze_pipeline(
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["issues_found"] == 0
        assert result["summaries"] == []


# ---------------------------------------------------------------------------
# handle_get_deal_overview
# ---------------------------------------------------------------------------


class TestGetDealOverview:
    def test_finds_by_name(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_deal_overview(
                query="Acme Expansion",
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["opportunity"]["name"] == "Acme Expansion"

    def test_returns_match_info(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_deal_overview(
                query="Acme Expansion",
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert "match_info" in result
        assert result["match_info"]["matched_name"] == "Acme Expansion"

    def test_crm_link_ends_with_opp_id(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_deal_overview(
                query="Acme Expansion",
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["crm_link"].endswith("opp-1")

    def test_not_found_returns_error(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_deal_overview(
                query="Nonexistent Deal",
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["error"] == "No matching opportunity found"
        assert "match_info" in result


# ---------------------------------------------------------------------------
# handle_get_company_overview
# ---------------------------------------------------------------------------


class TestGetCompanyOverview:
    def test_returns_grouped_deals_for_acme_corp(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_company_overview(
                company_name="Acme Corp",
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert result["company_name"] == "Acme Corp"
        assert len(result["deals"]) == 1  # only Acme Expansion matches
        assert result["deals"][0]["name"] == "Acme Expansion"

    def test_no_match_returns_error(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_company_overview(
                company_name="Unknown Inc",
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert "error" in result


# ---------------------------------------------------------------------------
# handle_get_deal_issues
# ---------------------------------------------------------------------------


class TestGetDealIssues:
    def test_returns_issues_for_flagged_deal(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_deal_issues(
                query="Acme Expansion",
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert len(result["issues"]) >= 1
        rule_ids = [i["rule_id"] for i in result["issues"]]
        # opp-1 has close_date in past + stale + no recent activity
        assert "close_date_past" in rule_ids


# ---------------------------------------------------------------------------
# handle_list_stale_deals
# ---------------------------------------------------------------------------


class TestListStaleDeals:
    def test_returns_stale_deals(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_list_stale_deals(
                min_days=None,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        # opp-1 is stale (21 days in PROPOSAL, threshold 7)
        assert len(result["stale_deals"]) >= 1

    def test_min_days_100_filters_to_zero(self, sample_contexts, rules_config):
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_list_stale_deals(
                min_days=100,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=CRM_URL,
                today=TODAY,
            )

        assert len(result["stale_deals"]) == 0


# ---------------------------------------------------------------------------
# handle_get_audit_history
# ---------------------------------------------------------------------------


class TestGetAuditHistory:
    def test_reads_jsonl_returns_runs(self, tmp_path: Path):
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

        result = handle_get_audit_history(limit=10, audit_dir=tmp_path)

        assert len(result["runs"]) == 1
        assert result["runs"][0]["run_id"] == "mcp-aabbccdd"


# ---------------------------------------------------------------------------
# handle_get_run_details
# ---------------------------------------------------------------------------


class TestGetRunDetails:
    def test_returns_run_and_issues(self, tmp_path: Path):
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
        ]
        _write_audit_records(tmp_path, records)

        result = handle_get_run_details(run_id="mcp-run1", audit_dir=tmp_path)

        assert result["run"]["run_id"] == "mcp-run1"
        assert len(result["issues"]) == 1

    def test_unknown_run_returns_error(self, tmp_path: Path):
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

        result = handle_get_run_details(run_id="mcp-unknown", audit_dir=tmp_path)

        assert "error" in result


# ---------------------------------------------------------------------------
# handle_get_rules_config
# ---------------------------------------------------------------------------


class TestGetRulesConfig:
    def test_returns_parsed_config(self, rules_yaml_path: Path):
        result = handle_get_rules_config(
            config_dir=rules_yaml_path.parent,
        )

        assert "excluded_stages" in result
        assert "rules" in result
        assert result["excluded_stages"] == ["CUSTOMER"]
        assert "stale_in_stage" in result["rules"]

    def test_missing_file_returns_error(self, tmp_path: Path):
        result = handle_get_rules_config(config_dir=tmp_path / "nonexistent")

        assert "error" in result


# ---------------------------------------------------------------------------
# CRM link with custom host
# ---------------------------------------------------------------------------


class TestCrmLinkCustomHost:
    def test_crm_url_produces_links_with_that_host(self, sample_contexts, rules_config):
        custom_url = "https://crm.public.com"
        with patch(
            "pipeline_coach.mcp.tools.fetch_all_contexts",
            return_value=sample_contexts,
        ):
            result = handle_get_deal_overview(
                query="Acme Expansion",
                use_llm=False,
                twenty_client=None,
                rules_config=rules_config,
                crm_url=custom_url,
                today=TODAY,
            )

        assert "crm.public.com" in result["crm_link"]
