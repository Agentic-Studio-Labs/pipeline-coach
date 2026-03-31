from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pipeline_coach.config import (
    AppConfig,
    EscalationConfig,
    RulesConfig,
    load_app_config,
    load_escalation_config,
    load_rules_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# load_rules_config
# ---------------------------------------------------------------------------

RULES_YAML = """\
    excluded_stages:
      - Closed Won
      - Closed Lost

    rules:
      stale_in_stage:
        enabled: true
        default_days: 14
        by_stage:
          Qualification: 21
          Negotiation: 7
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
def rules_yaml(tmp_path: Path) -> Path:
    return write_yaml(tmp_path, "rules.yaml", RULES_YAML)


def test_load_rules_config_stale_in_stage(rules_yaml: Path) -> None:
    cfg: RulesConfig = load_rules_config(rules_yaml)
    s = cfg.stale_in_stage
    assert s.enabled is True
    assert s.default_days == 14
    assert s.by_stage == {"Qualification": 21, "Negotiation": 7}
    assert s.severity == "medium"


def test_load_rules_config_close_date_past(rules_yaml: Path) -> None:
    cfg = load_rules_config(rules_yaml)
    c = cfg.close_date_past
    assert c.enabled is True
    assert c.severity == "high"


def test_load_rules_config_missing_decision_maker_by_stage(rules_yaml: Path) -> None:
    cfg = load_rules_config(rules_yaml)
    m = cfg.missing_decision_maker
    assert m.enabled is True
    assert m.by_stage == {"Proposal": True, "Negotiation": True}
    assert m.severity == "low"


def test_load_rules_config_close_date_soon_thresholds(rules_yaml: Path) -> None:
    cfg = load_rules_config(rules_yaml)
    c = cfg.close_date_soon_no_activity
    assert c.enabled is True
    assert c.close_date_soon_days == 7
    assert c.no_activity_days == 7
    assert c.severity == "high"


def test_load_rules_config_excluded_stages(rules_yaml: Path) -> None:
    cfg = load_rules_config(rules_yaml)
    assert cfg.excluded_stages == ["Closed Won", "Closed Lost"]


def test_load_rules_config_missing_required_key(tmp_path: Path) -> None:
    """A rule entry missing a required key should raise a clear error."""
    bad_yaml = write_yaml(
        tmp_path,
        "bad_rules.yaml",
        """\
        excluded_stages: []
        rules:
          stale_in_stage:
            enabled: true
            # default_days is intentionally missing
            by_stage: {}
            severity: medium
        """,
    )
    with pytest.raises((KeyError, TypeError)):
        load_rules_config(bad_yaml)


# ---------------------------------------------------------------------------
# load_escalation_config
# ---------------------------------------------------------------------------

ESCALATION_YAML = """\
    default_manager: manager@example.com
    overrides:
      ae1@example.com: vp@example.com
      ae2@example.com: director@example.com
    critical_amount_threshold: 75000.0
"""


@pytest.fixture()
def escalation_yaml(tmp_path: Path) -> Path:
    return write_yaml(tmp_path, "escalation.yaml", ESCALATION_YAML)


def test_load_escalation_config_default_manager(escalation_yaml: Path) -> None:
    cfg: EscalationConfig = load_escalation_config(escalation_yaml)
    assert cfg.default_manager == "manager@example.com"


def test_load_escalation_config_overrides(escalation_yaml: Path) -> None:
    cfg = load_escalation_config(escalation_yaml)
    assert cfg.overrides == {
        "ae1@example.com": "vp@example.com",
        "ae2@example.com": "director@example.com",
    }


def test_load_escalation_config_critical_threshold(escalation_yaml: Path) -> None:
    cfg = load_escalation_config(escalation_yaml)
    assert cfg.critical_amount_threshold == 75000.0


def test_escalation_get_manager_known_ae(escalation_yaml: Path) -> None:
    cfg = load_escalation_config(escalation_yaml)
    assert cfg.get_manager("ae1@example.com") == "vp@example.com"


def test_escalation_get_manager_unknown_ae_returns_default(escalation_yaml: Path) -> None:
    cfg = load_escalation_config(escalation_yaml)
    assert cfg.get_manager("unknown@example.com") == "manager@example.com"


# ---------------------------------------------------------------------------
# load_app_config
# ---------------------------------------------------------------------------

REQUIRED_ENV = {
    "TWENTY_API_URL": "https://api.twenty.example.com",
    "TWENTY_API_KEY": "twenty-key-123",
    "RESEND_API_KEY": "resend-key-456",
    "EMAIL_FROM": "coach@example.com",
}


def test_load_app_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    cfg: AppConfig = load_app_config()
    assert cfg.twenty_api_url == "https://api.twenty.example.com"
    assert cfg.twenty_api_key == "twenty-key-123"
    assert cfg.resend_api_key == "resend-key-456"
    assert cfg.email_from == "coach@example.com"


def test_load_app_config_optional_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    # Ensure optionals are NOT set
    for key in (
        "LLM_API_KEY",
        "LLM_MODEL",
        "CRM_PUBLIC_URL",
        "RUN_AT_HOUR",
        "AUDIT_REDACT_PII",
        "AUDIT_LOG_RETENTION_DAYS",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_app_config()
    assert cfg.llm_api_key is None
    assert cfg.crm_public_url is None
    assert cfg.llm_model == "openai/gpt-4o-mini"
    assert cfg.run_at_hour == 8
    assert cfg.audit_redact_pii is False
    assert cfg.audit_log_retention_days == 30


def test_load_app_config_crm_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CRM_PUBLIC_URL", "https://crm.example.com")
    cfg = load_app_config()
    assert cfg.crm_public_url == "https://crm.example.com"


def test_load_app_config_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TWENTY_API_URL", "TWENTY_API_KEY", "RESEND_API_KEY", "EMAIL_FROM"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(KeyError):
        load_app_config()
