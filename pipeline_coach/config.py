from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

# ---------------------------------------------------------------------------
# Rule config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StaleInStageConfig:
    enabled: bool
    default_days: int
    by_stage: dict[str, int]
    severity: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class NoRecentActivityConfig:
    enabled: bool
    days: int
    severity: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class CloseDatePastConfig:
    enabled: bool
    severity: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class CloseDateSoonNoActivityConfig:
    enabled: bool
    close_date_soon_days: int
    no_activity_days: int
    severity: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class MissingFieldConfig:
    enabled: bool
    severity: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class MissingDecisionMakerConfig:
    enabled: bool
    by_stage: dict[str, bool]
    severity: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class RulesConfig:
    stale_in_stage: StaleInStageConfig
    no_recent_activity: NoRecentActivityConfig
    close_date_past: CloseDatePastConfig
    close_date_soon_no_activity: CloseDateSoonNoActivityConfig
    missing_amount: MissingFieldConfig
    missing_close_date: MissingFieldConfig
    missing_decision_maker: MissingDecisionMakerConfig
    excluded_stages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# EscalationConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationConfig:
    default_manager: str
    overrides: dict[str, str] = field(default_factory=dict)
    critical_amount_threshold: float = 50_000.0

    def get_manager(self, ae_email: str) -> str:
        return self.overrides.get(ae_email, self.default_manager)


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppConfig:
    twenty_api_url: str
    twenty_api_key: str
    resend_api_key: str
    email_from: str
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-4o-mini"
    run_at_hour: int = 8
    audit_redact_pii: bool = False
    audit_log_retention_days: int = 30


# ---------------------------------------------------------------------------
# Loading functions
# ---------------------------------------------------------------------------


def load_app_config() -> AppConfig:
    """Read AppConfig from environment variables. Raises KeyError for missing required vars."""
    return AppConfig(
        twenty_api_url=os.environ["TWENTY_API_URL"],
        twenty_api_key=os.environ["TWENTY_API_KEY"],
        resend_api_key=os.environ["RESEND_API_KEY"],
        email_from=os.environ["EMAIL_FROM"],
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
        run_at_hour=int(os.environ.get("RUN_AT_HOUR", "8")),
        audit_redact_pii=os.environ.get("AUDIT_REDACT_PII", "false").lower() == "true",
        audit_log_retention_days=int(os.environ.get("AUDIT_LOG_RETENTION_DAYS", "30")),
    )


def load_rules_config(path: Path) -> RulesConfig:
    """Parse a rules YAML file into a RulesConfig. Raises KeyError on missing required keys."""
    data = yaml.safe_load(path.read_text())
    excluded_stages: list[str] = data.get("excluded_stages", [])
    rules = data["rules"]

    sis = rules["stale_in_stage"]
    no_act = rules["no_recent_activity"]
    cdp = rules["close_date_past"]
    cdsa = rules["close_date_soon_no_activity"]
    ma = rules["missing_amount"]
    mcd = rules["missing_close_date"]
    mdm = rules["missing_decision_maker"]

    return RulesConfig(
        stale_in_stage=StaleInStageConfig(
            enabled=sis["enabled"],
            default_days=sis["default_days"],
            by_stage=dict(sis.get("by_stage") or {}),
            severity=sis["severity"],
        ),
        no_recent_activity=NoRecentActivityConfig(
            enabled=no_act["enabled"],
            days=no_act["days"],
            severity=no_act["severity"],
        ),
        close_date_past=CloseDatePastConfig(
            enabled=cdp["enabled"],
            severity=cdp["severity"],
        ),
        close_date_soon_no_activity=CloseDateSoonNoActivityConfig(
            enabled=cdsa["enabled"],
            close_date_soon_days=cdsa["close_date_soon_days"],
            no_activity_days=cdsa["no_activity_days"],
            severity=cdsa["severity"],
        ),
        missing_amount=MissingFieldConfig(
            enabled=ma["enabled"],
            severity=ma["severity"],
        ),
        missing_close_date=MissingFieldConfig(
            enabled=mcd["enabled"],
            severity=mcd["severity"],
        ),
        missing_decision_maker=MissingDecisionMakerConfig(
            enabled=mdm["enabled"],
            by_stage=dict(mdm.get("by_stage") or {}),
            severity=mdm["severity"],
        ),
        excluded_stages=excluded_stages,
    )


def load_escalation_config(path: Path) -> EscalationConfig:
    """Parse an escalation YAML file into an EscalationConfig."""
    raw = yaml.safe_load(path.read_text())
    data = raw.get("escalation", raw)
    return EscalationConfig(
        default_manager=data["default_manager"],
        overrides=dict(data.get("overrides") or {}),
        critical_amount_threshold=float(data.get("critical_amount_threshold", 50_000.0)),
    )
