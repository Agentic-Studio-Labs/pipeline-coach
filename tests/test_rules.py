from __future__ import annotations

from datetime import date

import pytest
from pipeline_coach.hygiene.rules import evaluate_opportunity

from pipeline_coach.config import RulesConfig, load_rules_config
from pipeline_coach.models import OpportunityContext

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


@pytest.fixture()
def rules_config(tmp_path) -> RulesConfig:
    config_file = tmp_path / "rules.yaml"
    config_file.write_text(RULES_YAML)
    return load_rules_config(config_file)


def _opp(**kwargs) -> OpportunityContext:
    defaults = dict(
        id="opp-test",
        name="Test Opp",
        amount=10_000.0,
        stage="Discovery",
        owner_email="rep@demo.com",
        close_date=date(2026, 12, 31),
        days_in_stage=1,
        days_since_last_activity=1,
        has_decision_maker=True,
    )
    defaults.update(kwargs)
    return OpportunityContext(**defaults)


class TestStaleInStage:
    def test_fires_with_stage_override(self, rules_config: RulesConfig) -> None:
        opp = _opp(stage="Negotiation", days_in_stage=10)
        issues = evaluate_opportunity(opp, rules_config)
        rule_ids = [i.rule_id for i in issues]
        assert "stale_in_stage" in rule_ids
        stale = next(i for i in issues if i.rule_id == "stale_in_stage")
        assert stale.details["threshold"] == 7
        assert stale.details["days"] == 10
        assert stale.details["stage"] == "Negotiation"

    def test_no_issue_under_threshold(self, rules_config: RulesConfig) -> None:
        opp = _opp(stage="Negotiation", days_in_stage=5)
        issues = evaluate_opportunity(opp, rules_config)
        assert not any(i.rule_id == "stale_in_stage" for i in issues)

    def test_uses_default_for_unknown_stage(self, rules_config: RulesConfig) -> None:
        # default_days=14; Discovery has no override → threshold=14
        opp = _opp(stage="Discovery", days_in_stage=15)
        issues = evaluate_opportunity(opp, rules_config)
        rule_ids = [i.rule_id for i in issues]
        assert "stale_in_stage" in rule_ids
        stale = next(i for i in issues if i.rule_id == "stale_in_stage")
        assert stale.details["threshold"] == 14


class TestNoRecentActivity:
    def test_fires_when_no_recent_activity(self, rules_config: RulesConfig) -> None:
        opp = _opp(days_since_last_activity=8)
        issues = evaluate_opportunity(opp, rules_config)
        assert any(i.rule_id == "no_recent_activity" for i in issues)

    def test_passes_with_recent_activity(self, rules_config: RulesConfig) -> None:
        opp = _opp(days_since_last_activity=3)
        issues = evaluate_opportunity(opp, rules_config)
        assert not any(i.rule_id == "no_recent_activity" for i in issues)

    def test_skipped_when_none(self, rules_config: RulesConfig) -> None:
        opp = _opp(days_since_last_activity=None)
        issues = evaluate_opportunity(opp, rules_config)
        assert not any(i.rule_id == "no_recent_activity" for i in issues)


class TestCloseDatePast:
    def test_fires_when_close_date_past(self, rules_config: RulesConfig) -> None:
        opp = _opp(close_date=date(2026, 1, 1))
        issues = evaluate_opportunity(opp, rules_config, today=date(2026, 3, 30))
        assert any(i.rule_id == "close_date_past" for i in issues)

    def test_passes_when_close_date_future(self, rules_config: RulesConfig) -> None:
        opp = _opp(close_date=date(2026, 12, 31))
        issues = evaluate_opportunity(opp, rules_config, today=date(2026, 3, 30))
        assert not any(i.rule_id == "close_date_past" for i in issues)


class TestCloseDateSoonNoActivity:
    def test_fires_when_close_soon_and_no_activity(self, rules_config: RulesConfig) -> None:
        # close_date 5 days away (within 7), last activity 10 days ago (> 7)
        opp = _opp(close_date=date(2026, 4, 4), days_since_last_activity=10)
        issues = evaluate_opportunity(opp, rules_config, today=date(2026, 3, 30))
        assert any(i.rule_id == "close_date_soon_no_activity" for i in issues)

    def test_passes_with_recent_activity(self, rules_config: RulesConfig) -> None:
        # close_date 5 days away but activity only 3 days ago (≤ 7)
        opp = _opp(close_date=date(2026, 4, 4), days_since_last_activity=3)
        issues = evaluate_opportunity(opp, rules_config, today=date(2026, 3, 30))
        assert not any(i.rule_id == "close_date_soon_no_activity" for i in issues)


class TestMissingFields:
    def test_missing_amount_none(self, rules_config: RulesConfig) -> None:
        opp = _opp(amount=None)
        issues = evaluate_opportunity(opp, rules_config)
        assert any(i.rule_id == "missing_amount" for i in issues)

    def test_zero_amount(self, rules_config: RulesConfig) -> None:
        opp = _opp(amount=0.0)
        issues = evaluate_opportunity(opp, rules_config)
        assert any(i.rule_id == "missing_amount" for i in issues)

    def test_missing_close_date(self, rules_config: RulesConfig) -> None:
        opp = _opp(close_date=None)
        issues = evaluate_opportunity(opp, rules_config)
        assert any(i.rule_id == "missing_close_date" for i in issues)

    def test_missing_decision_maker_proposal(self, rules_config: RulesConfig) -> None:
        opp = _opp(stage="Proposal", has_decision_maker=False)
        issues = evaluate_opportunity(opp, rules_config)
        assert any(i.rule_id == "missing_decision_maker" for i in issues)

    def test_no_decision_maker_check_qualification(self, rules_config: RulesConfig) -> None:
        # Qualification is not in by_stage → rule should not fire
        opp = _opp(stage="Qualification", has_decision_maker=False)
        issues = evaluate_opportunity(opp, rules_config)
        assert not any(i.rule_id == "missing_decision_maker" for i in issues)


class TestCleanOpp:
    def test_clean_opp_no_issues(
        self, rules_config: RulesConfig, sample_opp_context_clean: OpportunityContext
    ) -> None:
        issues = evaluate_opportunity(
            sample_opp_context_clean, rules_config, today=date(2026, 3, 30)
        )
        assert issues == []
