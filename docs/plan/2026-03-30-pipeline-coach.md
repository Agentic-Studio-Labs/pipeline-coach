# Pipeline Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily pipeline hygiene coach that connects to Twenty CRM, detects deal issues, and emails AEs prioritized action lists with manager escalation for critical deals.

**Architecture:** LangGraph state machine with 5-way parallel data fetch, deterministic rule engine, DSPy-powered action suggestions with quality gate retry loop, and conditional escalation routing. Single Python package (`pipeline_coach/`) deployed alongside Twenty via Docker Compose.

**Tech Stack:** Python 3.12, LangGraph, DSPy 3.x, httpx (sync), Pydantic, Resend, PyYAML, APScheduler, structlog, pytest

**Design spec:** `docs/superpowers/specs/2026-03-30-pipeline-coach-design.md`

---

## File Structure

```
pipeline-coach/
├── docker-compose.yml              # Twenty + Postgres + Pipeline Coach services
├── Dockerfile                      # Pipeline Coach container
├── .env.example                    # Template for secrets + infra config
├── .gitignore
├── LICENSE                         # Apache 2.0
├── README.md
├── pyproject.toml                  # Package definition + deps
├── config/
│   ├── rules.yaml                  # Hygiene rules with per-stage thresholds
│   └── escalation.yaml             # AE→manager mapping + critical threshold
├── pipeline_coach/
│   ├── __init__.py
│   ├── __main__.py                 # Entry: python -m pipeline_coach [--once]
│   ├── run_once.py                 # Single pipeline execution
│   ├── scheduler.py                # APScheduler daily cron
│   ├── smoke_test.py               # Compose smoke test entrypoint
│   ├── show_recent.py              # CLI: view recent briefs/audit for an owner
│   ├── config.py                   # Load env vars + YAML configs into typed models
│   ├── models.py                   # OpportunityContext, Issue, IssueSummary
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── twenty_client.py        # GraphQL client with pagination
│   │   └── normalizer.py           # Raw GQL → OpportunityContext[]
│   ├── hygiene/
│   │   ├── __init__.py
│   │   ├── rules.py                # YAML-driven rule evaluation
│   │   └── priority.py             # Priority scoring heuristic
│   ├── coach/
│   │   ├── __init__.py
│   │   ├── actions.py              # DSPy SuggestAction + fallback
│   │   ├── quality_gate.py         # Validate LLM output
│   │   └── brief.py                # Render AE + manager brief text
│   ├── delivery/
│   │   ├── __init__.py
│   │   ├── email_client.py         # Resend API wrapper
│   │   └── router.py               # Route: AE briefs + manager escalations
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── state.py                # PipelineState TypedDict
│   │   └── graph.py                # LangGraph state machine
│   └── observability/
│       ├── __init__.py
│       └── logger.py               # Structured JSON logging + audit
├── scripts/
│   └── seed_twenty.py              # Seed Twenty with sample data
├── tests/
│   ├── conftest.py                 # Shared fixtures
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_twenty_client.py
│   ├── test_normalizer.py
│   ├── test_rules.py
│   ├── test_priority.py
│   ├── test_actions.py
│   ├── test_quality_gate.py
│   ├── test_brief.py
│   ├── test_email_client.py
│   ├── test_router.py
│   └── test_workflow.py
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-03-30-pipeline-coach-design.md
        └── plans/
            └── 2026-03-30-pipeline-coach.md
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `LICENSE`, `config/rules.yaml`, `config/escalation.yaml`
- Create: all `__init__.py` files for the package tree
- Create: `tests/conftest.py`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/jm/Projects/pipeline-coach
git init
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pipeline-coach"
version = "0.1.0"
description = "Daily pipeline hygiene coach for Twenty CRM"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = [
    "langgraph>=0.2.0",
    "dspy>=3.0.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
    "resend>=2.0.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
    "apscheduler>=3.10.0",
    "structlog>=24.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.6.0",
]

[tool.ruff]
line-length = 99
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create .gitignore**

```
__pycache__/
*.pyc
.env
*.egg-info/
dist/
.pytest_cache/
.ruff_cache/
data/
scripts/seed_output.json
.venv/
```

- [ ] **Step 4: Create .env.example**

```bash
# Twenty CRM
TWENTY_API_URL=http://twenty:3000
TWENTY_API_KEY=your-twenty-api-key

# Resend
RESEND_API_KEY=your-resend-api-key
EMAIL_FROM=pipeline-coach@yourdomain.com

# LLM (for DSPy)
LLM_API_KEY=your-llm-api-key
LLM_MODEL=openai/gpt-4o-mini

# Scheduling
RUN_AT_HOUR=08

# Optional privacy controls
AUDIT_REDACT_PII=false
AUDIT_LOG_RETENTION_DAYS=30
```

- [ ] **Step 5: Create LICENSE (Apache 2.0)**

Download or write the standard Apache 2.0 license text with copyright line:
```
Copyright 2026 Pipeline Coach Contributors
```

- [ ] **Step 6: Create config/rules.yaml**

```yaml
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
```

- [ ] **Step 7: Create config/escalation.yaml**

```yaml
escalation:
  default_manager: vp-sales@demo.com
  overrides:
    alex@demo.com: manager-a@demo.com
    jordan@demo.com: manager-b@demo.com
  critical_amount_threshold: 50000
```

- [ ] **Step 8: Create package __init__.py files**

Create empty `__init__.py` in:
- `pipeline_coach/`
- `pipeline_coach/ingestion/`
- `pipeline_coach/hygiene/`
- `pipeline_coach/coach/`
- `pipeline_coach/delivery/`
- `pipeline_coach/workflow/`
- `pipeline_coach/observability/`

- [ ] **Step 9: Create tests/conftest.py with shared fixtures**

```python
from __future__ import annotations

from datetime import date, datetime

import pytest

from pipeline_coach.models import Issue, IssueSummary, OpportunityContext


@pytest.fixture()
def sample_opp_context() -> OpportunityContext:
    return OpportunityContext(
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


@pytest.fixture()
def sample_opp_context_clean() -> OpportunityContext:
    return OpportunityContext(
        id="opp-clean",
        name="Brightwave Onboarding",
        amount=50_000.0,
        stage="Discovery",
        owner_email="jordan@demo.com",
        owner_name="Jordan Lee",
        company_name="Brightwave",
        close_date=date(2026, 5, 1),
        last_activity_at=datetime(2026, 3, 28, 14, 0),
        days_in_stage=3,
        days_since_last_activity=2,
        has_decision_maker=True,
    )


@pytest.fixture()
def sample_opp_context_missing_fields() -> OpportunityContext:
    return OpportunityContext(
        id="opp-missing",
        name="NimbusHQ Deal",
        amount=None,
        stage="Proposal",
        owner_email="alex@demo.com",
        owner_name="Alex Doe",
        company_name="NimbusHQ",
        close_date=None,
        last_activity_at=None,
        days_in_stage=30,
        days_since_last_activity=None,
        has_decision_maker=False,
    )


@pytest.fixture()
def sample_issue_stale() -> Issue:
    return Issue(
        rule_id="stale_in_stage",
        severity="medium",
        message="Stale in Negotiation: 21 days (threshold: 7)",
        details={"stage": "Negotiation", "days": 21, "threshold": 7},
    )


@pytest.fixture()
def sample_issue_critical() -> Issue:
    return Issue(
        rule_id="close_date_past",
        severity="high",
        message="Close date 2026-03-15 is in the past",
        details={"close_date": "2026-03-15"},
    )


@pytest.fixture()
def sample_issue_summary(
    sample_opp_context: OpportunityContext,
    sample_issue_stale: Issue,
    sample_issue_critical: Issue,
) -> IssueSummary:
    return IssueSummary(
        opportunity_id="opp-1",
        opportunity_name="Acme Corp Expansion",
        owner_email="alex@demo.com",
        priority="high",
        issues=[sample_issue_critical, sample_issue_stale],
        context=sample_opp_context,
        suggested_action="Schedule a call with the Acme team to confirm the deal timeline.",
    )
```

- [ ] **Step 10: Install the package in dev mode**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .gitignore .env.example LICENSE config/ pipeline_coach/ tests/conftest.py
git commit -m "feat: project scaffolding with package structure, config files, and test fixtures"
```

---

## Task 2: Data Models

**Files:**
- Create: `pipeline_coach/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write tests for model validation**

```python
# tests/test_models.py
from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from pipeline_coach.models import Issue, IssueSummary, OpportunityContext


class TestOpportunityContext:
    def test_create_with_all_fields(self, sample_opp_context: OpportunityContext) -> None:
        assert sample_opp_context.id == "opp-1"
        assert sample_opp_context.amount == 120_000.0
        assert sample_opp_context.stage == "Negotiation"
        assert sample_opp_context.owner_email == "alex@demo.com"

    def test_create_with_minimal_fields(self) -> None:
        ctx = OpportunityContext(
            id="opp-min",
            name="Minimal Deal",
            stage="Qualification",
            owner_email="rep@demo.com",
        )
        assert ctx.amount is None
        assert ctx.close_date is None
        assert ctx.last_activity_at is None

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            OpportunityContext(id="x", name="X", stage="Y")  # missing owner_email

    def test_serialization_round_trip(self, sample_opp_context: OpportunityContext) -> None:
        data = sample_opp_context.model_dump()
        restored = OpportunityContext.model_validate(data)
        assert restored == sample_opp_context


class TestIssue:
    def test_create_issue(self, sample_issue_stale: Issue) -> None:
        assert sample_issue_stale.rule_id == "stale_in_stage"
        assert sample_issue_stale.severity == "medium"
        assert sample_issue_stale.details["days"] == 21

    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(ValidationError):
            Issue(rule_id="x", severity="critical", message="bad")

    def test_empty_details_default(self) -> None:
        issue = Issue(rule_id="test", severity="low", message="test msg")
        assert issue.details == {}


class TestIssueSummary:
    def test_create_summary(self, sample_issue_summary: IssueSummary) -> None:
        assert sample_issue_summary.priority == "high"
        assert len(sample_issue_summary.issues) == 2
        assert sample_issue_summary.issues[0].rule_id == "close_date_past"

    def test_summary_without_suggested_action(
        self, sample_opp_context: OpportunityContext, sample_issue_stale: Issue
    ) -> None:
        summary = IssueSummary(
            opportunity_id="opp-1",
            opportunity_name="Acme Corp Expansion",
            owner_email="alex@demo.com",
            priority="medium",
            issues=[sample_issue_stale],
            context=sample_opp_context,
        )
        assert summary.suggested_action is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline_coach.models'`

- [ ] **Step 3: Implement models.py**

```python
# pipeline_coach/models.py
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class OpportunityContext(BaseModel):
    id: str
    name: str
    amount: float | None = None
    stage: str
    owner_email: str
    owner_name: str | None = None
    company_name: str | None = None
    close_date: date | None = None
    last_activity_at: datetime | None = None
    days_in_stage: int | None = None
    days_since_last_activity: int | None = None
    has_decision_maker: bool | None = None


class Issue(BaseModel):
    rule_id: str
    severity: Literal["high", "medium", "low"]
    message: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class IssueSummary(BaseModel):
    opportunity_id: str
    opportunity_name: str
    owner_email: str
    priority: Literal["high", "medium", "low"]
    issues: list[Issue]
    context: OpportunityContext
    suggested_action: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/models.py tests/test_models.py
git commit -m "feat: add Pydantic data models (OpportunityContext, Issue, IssueSummary)"
```

---

## Task 3: Config Module

**Files:**
- Create: `pipeline_coach/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write tests for config loading**

```python
# tests/test_config.py
from __future__ import annotations

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


@pytest.fixture()
def rules_yaml(tmp_path: Path) -> Path:
    content = """\
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
    p = tmp_path / "rules.yaml"
    p.write_text(content)
    return p


@pytest.fixture()
def escalation_yaml(tmp_path: Path) -> Path:
    content = """\
escalation:
  default_manager: vp-sales@demo.com
  overrides:
    alex@demo.com: manager-a@demo.com
    jordan@demo.com: manager-b@demo.com
  critical_amount_threshold: 50000
"""
    p = tmp_path / "escalation.yaml"
    p.write_text(content)
    return p


class TestLoadRulesConfig:
    def test_loads_stale_in_stage(self, rules_yaml: Path) -> None:
        cfg = load_rules_config(rules_yaml)
        assert cfg.stale_in_stage.enabled is True
        assert cfg.stale_in_stage.default_days == 14
        assert cfg.stale_in_stage.by_stage["Negotiation"] == 7
        assert cfg.stale_in_stage.severity == "medium"

    def test_loads_close_date_past(self, rules_yaml: Path) -> None:
        cfg = load_rules_config(rules_yaml)
        assert cfg.close_date_past.enabled is True
        assert cfg.close_date_past.severity == "high"

    def test_loads_missing_decision_maker_by_stage(self, rules_yaml: Path) -> None:
        cfg = load_rules_config(rules_yaml)
        assert cfg.missing_decision_maker.by_stage["Proposal"] is True
        assert "Discovery" not in cfg.missing_decision_maker.by_stage

    def test_loads_close_date_soon_thresholds(self, rules_yaml: Path) -> None:
        cfg = load_rules_config(rules_yaml)
        assert cfg.close_date_soon_no_activity.close_date_soon_days == 7
        assert cfg.close_date_soon_no_activity.no_activity_days == 7


class TestLoadEscalationConfig:
    def test_loads_default_manager(self, escalation_yaml: Path) -> None:
        cfg = load_escalation_config(escalation_yaml)
        assert cfg.default_manager == "vp-sales@demo.com"

    def test_loads_overrides(self, escalation_yaml: Path) -> None:
        cfg = load_escalation_config(escalation_yaml)
        assert cfg.overrides["alex@demo.com"] == "manager-a@demo.com"

    def test_loads_critical_threshold(self, escalation_yaml: Path) -> None:
        cfg = load_escalation_config(escalation_yaml)
        assert cfg.critical_amount_threshold == 50_000.0

    def test_get_manager_for_known_ae(self, escalation_yaml: Path) -> None:
        cfg = load_escalation_config(escalation_yaml)
        assert cfg.get_manager("alex@demo.com") == "manager-a@demo.com"

    def test_get_manager_for_unknown_ae_returns_default(
        self, escalation_yaml: Path
    ) -> None:
        cfg = load_escalation_config(escalation_yaml)
        assert cfg.get_manager("unknown@demo.com") == "vp-sales@demo.com"


class TestLoadAppConfig:
    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TWENTY_API_URL", "http://localhost:3000")
        monkeypatch.setenv("TWENTY_API_KEY", "key123")
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        monkeypatch.setenv("EMAIL_FROM", "coach@test.com")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
        monkeypatch.setenv("RUN_AT_HOUR", "9")

        cfg = load_app_config()
        assert cfg.twenty_api_url == "http://localhost:3000"
        assert cfg.twenty_api_key == "key123"
        assert cfg.resend_api_key == "re_test"
        assert cfg.run_at_hour == 9
        assert cfg.llm_api_key == "sk-test"

    def test_defaults_when_optional_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TWENTY_API_URL", "http://localhost:3000")
        monkeypatch.setenv("TWENTY_API_KEY", "key123")
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        monkeypatch.setenv("EMAIL_FROM", "coach@test.com")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("RUN_AT_HOUR", raising=False)

        cfg = load_app_config()
        assert cfg.llm_api_key is None
        assert cfg.llm_model == "openai/gpt-4o-mini"
        assert cfg.run_at_hour == 8

    def test_missing_required_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TWENTY_API_URL", raising=False)
        monkeypatch.delenv("TWENTY_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)
        with pytest.raises(KeyError):
            load_app_config()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement config.py**

```python
# pipeline_coach/config.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


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


@dataclass(frozen=True)
class EscalationConfig:
    default_manager: str
    overrides: dict[str, str] = field(default_factory=dict)
    critical_amount_threshold: float = 50_000.0

    def get_manager(self, ae_email: str) -> str:
        return self.overrides.get(ae_email, self.default_manager)


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


def load_app_config() -> AppConfig:
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
    with open(path) as f:
        data = yaml.safe_load(f)
    r = data["rules"]
    return RulesConfig(
        stale_in_stage=StaleInStageConfig(
            enabled=r["stale_in_stage"]["enabled"],
            default_days=r["stale_in_stage"]["default_days"],
            by_stage=r["stale_in_stage"].get("by_stage", {}),
            severity=r["stale_in_stage"]["severity"],
        ),
        no_recent_activity=NoRecentActivityConfig(
            enabled=r["no_recent_activity"]["enabled"],
            days=r["no_recent_activity"]["days"],
            severity=r["no_recent_activity"]["severity"],
        ),
        close_date_past=CloseDatePastConfig(
            enabled=r["close_date_past"]["enabled"],
            severity=r["close_date_past"]["severity"],
        ),
        close_date_soon_no_activity=CloseDateSoonNoActivityConfig(
            enabled=r["close_date_soon_no_activity"]["enabled"],
            close_date_soon_days=r["close_date_soon_no_activity"]["close_date_soon_days"],
            no_activity_days=r["close_date_soon_no_activity"]["no_activity_days"],
            severity=r["close_date_soon_no_activity"]["severity"],
        ),
        missing_amount=MissingFieldConfig(
            enabled=r["missing_amount"]["enabled"],
            severity=r["missing_amount"]["severity"],
        ),
        missing_close_date=MissingFieldConfig(
            enabled=r["missing_close_date"]["enabled"],
            severity=r["missing_close_date"]["severity"],
        ),
        missing_decision_maker=MissingDecisionMakerConfig(
            enabled=r["missing_decision_maker"]["enabled"],
            by_stage=r["missing_decision_maker"].get("by_stage", {}),
            severity=r["missing_decision_maker"]["severity"],
        ),
    )


def load_escalation_config(path: Path) -> EscalationConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    esc = data["escalation"]
    return EscalationConfig(
        default_manager=esc["default_manager"],
        overrides=esc.get("overrides", {}),
        critical_amount_threshold=float(esc.get("critical_amount_threshold", 50_000)),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/config.py tests/test_config.py
git commit -m "feat: config module — load app settings, rules, and escalation from env/YAML"
```

---

## Task 4: Twenty GraphQL Client

**Files:**
- Create: `pipeline_coach/ingestion/twenty_client.py`
- Create: `tests/test_twenty_client.py`

**Note:** Twenty's GraphQL endpoint is at `/graphql`. Auth is `Authorization: Bearer <key>`. Pagination follows Relay Connection spec (edges/node/pageInfo with cursor-based forward pagination, max 200/page). All field names are camelCase.

- [ ] **Step 1: Write tests for the GraphQL client**

```python
# tests/test_twenty_client.py
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from pipeline_coach.ingestion.twenty_client import TwentyClient


def _make_connection_response(nodes: list[dict], has_next: bool = False) -> dict:
    edges = [{"cursor": f"cursor-{i}", "node": n} for i, n in enumerate(nodes)]
    return {
        "edges": edges,
        "pageInfo": {
            "hasNextPage": has_next,
            "endCursor": edges[-1]["cursor"] if edges else None,
        },
    }


@pytest.fixture()
def mock_httpx_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    return mock


@pytest.fixture()
def client() -> TwentyClient:
    return TwentyClient(base_url="http://twenty:3000", api_key="test-key")


class TestTwentyClientQuery:
    def test_single_page_fetch(self, client: TwentyClient, monkeypatch: pytest.MonkeyPatch) -> None:
        response_data = {
            "data": {
                "companies": _make_connection_response(
                    [{"id": "c1", "name": "Acme Corp"}, {"id": "c2", "name": "Northwind"}],
                    has_next=False,
                )
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        monkeypatch.setattr(client, "_http", mock_http)

        nodes = client.fetch_all("companies", "{ id name }")
        assert len(nodes) == 2
        assert nodes[0]["name"] == "Acme Corp"

    def test_multi_page_fetch(self, client: TwentyClient, monkeypatch: pytest.MonkeyPatch) -> None:
        page1 = {
            "data": {
                "companies": _make_connection_response(
                    [{"id": "c1", "name": "Acme"}], has_next=True
                )
            }
        }
        page2 = {
            "data": {
                "companies": _make_connection_response(
                    [{"id": "c2", "name": "Northwind"}], has_next=False
                )
            }
        }
        mock_response1 = MagicMock()
        mock_response1.json.return_value = page1
        mock_response1.raise_for_status = MagicMock()

        mock_response2 = MagicMock()
        mock_response2.json.return_value = page2
        mock_response2.raise_for_status = MagicMock()

        mock_http = MagicMock()
        mock_http.post.side_effect = [mock_response1, mock_response2]
        monkeypatch.setattr(client, "_http", mock_http)

        nodes = client.fetch_all("companies", "{ id name }")
        assert len(nodes) == 2
        assert nodes[1]["name"] == "Northwind"
        assert mock_http.post.call_count == 2

    def test_auth_header_sent(self, client: TwentyClient, monkeypatch: pytest.MonkeyPatch) -> None:
        response_data = {
            "data": {"companies": _make_connection_response([], has_next=False)}
        }
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        monkeypatch.setattr(client, "_http", mock_http)

        client.fetch_all("companies", "{ id name }")

        call_kwargs = mock_http.post.call_args
        assert call_kwargs is not None

    def test_graphql_error_raises(
        self, client: TwentyClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response_data = {"errors": [{"message": "Field not found"}]}
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        monkeypatch.setattr(client, "_http", mock_http)

        with pytest.raises(RuntimeError, match="GraphQL"):
            client.fetch_all("companies", "{ id name }")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_twenty_client.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement twenty_client.py**

```python
# pipeline_coach/ingestion/twenty_client.py
from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()

PAGE_SIZE = 200


class TwentyClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=f"{self._base_url}/graphql",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _query(self, query: str, variables: dict | None = None) -> dict:
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self._http.post("", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]

    def fetch_all(self, collection: str, fields: str) -> list[dict]:
        all_nodes: list[dict] = []
        cursor: str | None = None

        while True:
            after_clause = f', after: "{cursor}"' if cursor else ""
            query = (
                f"{{ {collection}(first: {PAGE_SIZE}{after_clause}) "
                f"{{ edges {{ cursor node {fields} }} "
                f"pageInfo {{ hasNextPage endCursor }} }} }}"
            )
            data = self._query(query)
            connection = data[collection]
            nodes = [edge["node"] for edge in connection["edges"]]
            all_nodes.extend(nodes)

            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

        logger.info("twenty_fetch_complete", collection=collection, count=len(all_nodes))
        return all_nodes

    def close(self) -> None:
        self._http.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_twenty_client.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/ingestion/twenty_client.py tests/test_twenty_client.py
git commit -m "feat: Twenty CRM GraphQL client with cursor-based pagination"
```

---

## Task 5: Normalizer

**Files:**
- Create: `pipeline_coach/ingestion/normalizer.py`
- Create: `tests/test_normalizer.py`

**Note:** Twenty uses `amountMicros`/`currencyCode` for amounts, `{ firstName, lastName }` for names, `{ primaryEmail }` for emails, and `taskTargets` to link tasks to opportunities. The normalizer is the single place that maps these conventions to `OpportunityContext`.

- [ ] **Step 1: Write tests for the normalizer**

```python
# tests/test_normalizer.py
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from pipeline_coach.ingestion.normalizer import normalize_opportunities


@pytest.fixture()
def raw_opportunities() -> list[dict]:
    return [
        {
            "id": "opp-1",
            "name": "Acme Expansion",
            "amount": {"amountMicros": 120_000_000_000, "currencyCode": "USD"},
            "stage": "Negotiation",
            "closeDate": "2026-03-15T00:00:00Z",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-03-09T00:00:00Z",
            "companyId": "comp-1",
            "pointOfContactId": "person-1",
            "ownerId": "member-1",
        },
        {
            "id": "opp-2",
            "name": "Northwind Upsell",
            "amount": None,
            "stage": "Proposal",
            "closeDate": None,
            "createdAt": "2026-02-01T00:00:00Z",
            "updatedAt": "2026-02-15T00:00:00Z",
            "companyId": "comp-2",
            "pointOfContactId": None,
            "ownerId": "member-2",
        },
    ]


@pytest.fixture()
def raw_companies() -> list[dict]:
    return [
        {"id": "comp-1", "name": "Acme Corp"},
        {"id": "comp-2", "name": "Northwind"},
    ]


@pytest.fixture()
def raw_people() -> list[dict]:
    return [
        {
            "id": "person-1",
            "name": {"firstName": "Jane", "lastName": "Smith"},
            "emails": {"primaryEmail": "jane@acme.com"},
            "jobTitle": "VP Engineering",
            "companyId": "comp-1",
        },
    ]


@pytest.fixture()
def raw_workspace_members() -> list[dict]:
    return [
        {
            "id": "member-1",
            "name": {"firstName": "Alex", "lastName": "Doe"},
            "userEmail": "alex@demo.com",
        },
        {
            "id": "member-2",
            "name": {"firstName": "Jordan", "lastName": "Lee"},
            "userEmail": "jordan@demo.com",
        },
    ]


@pytest.fixture()
def raw_tasks() -> list[dict]:
    return [
        {
            "id": "task-1",
            "createdAt": "2026-03-12T10:00:00Z",
            "status": "DONE",
            "taskTargets": {
                "edges": [{"node": {"opportunityId": "opp-1"}}]
            },
        },
    ]


class TestNormalize:
    def test_basic_normalization(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            opportunities=raw_opportunities,
            companies=raw_companies,
            people=raw_people,
            workspace_members=raw_workspace_members,
            tasks=raw_tasks,
            today=today,
        )
        assert len(contexts) == 2

    def test_amount_conversion_from_micros(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        acme = next(c for c in contexts if c.id == "opp-1")
        assert acme.amount == 120_000.0

    def test_null_amount(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        northwind = next(c for c in contexts if c.id == "opp-2")
        assert northwind.amount is None

    def test_owner_mapped_from_workspace_member(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        acme = next(c for c in contexts if c.id == "opp-1")
        assert acme.owner_email == "alex@demo.com"
        assert acme.owner_name == "Alex Doe"

    def test_company_name_resolved(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        acme = next(c for c in contexts if c.id == "opp-1")
        assert acme.company_name == "Acme Corp"

    def test_days_in_stage_from_updated_at(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        acme = next(c for c in contexts if c.id == "opp-1")
        assert acme.days_in_stage == 21  # 2026-03-09 to 2026-03-30

    def test_last_activity_from_tasks(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        acme = next(c for c in contexts if c.id == "opp-1")
        assert acme.last_activity_at == datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc)
        assert acme.days_since_last_activity == 18

    def test_no_tasks_yields_none_activity(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        northwind = next(c for c in contexts if c.id == "opp-2")
        assert northwind.last_activity_at is None
        assert northwind.days_since_last_activity is None

    def test_has_decision_maker_from_point_of_contact(
        self,
        raw_opportunities: list[dict],
        raw_companies: list[dict],
        raw_people: list[dict],
        raw_workspace_members: list[dict],
        raw_tasks: list[dict],
    ) -> None:
        today = date(2026, 3, 30)
        contexts = normalize_opportunities(
            raw_opportunities, raw_companies, raw_people,
            raw_workspace_members, raw_tasks, today,
        )
        acme = next(c for c in contexts if c.id == "opp-1")
        assert acme.has_decision_maker is True
        northwind = next(c for c in contexts if c.id == "opp-2")
        assert northwind.has_decision_maker is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_normalizer.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement normalizer.py**

```python
# pipeline_coach/ingestion/normalizer.py
from __future__ import annotations

from datetime import date, datetime, timezone

from pipeline_coach.models import OpportunityContext


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(raw: str | None) -> date | None:
    dt = _parse_dt(raw)
    return dt.date() if dt else None


def _extract_amount(raw: dict | None) -> float | None:
    if not raw or raw.get("amountMicros") is None:
        return None
    return raw["amountMicros"] / 1_000_000


def _full_name(raw: dict | None) -> str | None:
    if not raw:
        return None
    first = raw.get("firstName", "") or ""
    last = raw.get("lastName", "") or ""
    name = f"{first} {last}".strip()
    return name or None


def normalize_opportunities(
    *,
    opportunities: list[dict],
    companies: list[dict],
    people: list[dict],
    workspace_members: list[dict],
    tasks: list[dict],
    today: date,
) -> list[OpportunityContext]:
    company_map = {c["id"]: c["name"] for c in companies}
    member_map = {
        m["id"]: {"email": m["userEmail"], "name": _full_name(m.get("name"))}
        for m in workspace_members
    }
    poc_set = {p["id"] for p in people}

    # Build opp_id → latest task created_at
    opp_latest_activity: dict[str, datetime] = {}
    for task in tasks:
        task_dt = _parse_dt(task.get("createdAt"))
        if not task_dt:
            continue
        targets = task.get("taskTargets", {}).get("edges", [])
        for edge in targets:
            opp_id = edge.get("node", {}).get("opportunityId")
            if opp_id:
                existing = opp_latest_activity.get(opp_id)
                if existing is None or task_dt > existing:
                    opp_latest_activity[opp_id] = task_dt

    contexts: list[OpportunityContext] = []
    for opp in opportunities:
        opp_id = opp["id"]
        owner_id = opp.get("ownerId")
        owner_info = member_map.get(owner_id, {}) if owner_id else {}
        owner_email = owner_info.get("email", "unknown@unknown.com")

        updated_at = _parse_dt(opp.get("updatedAt"))
        days_in_stage = (today - updated_at.date()).days if updated_at else None

        last_activity = opp_latest_activity.get(opp_id)
        days_since_activity = (
            (today - last_activity.date()).days if last_activity else None
        )

        poc_id = opp.get("pointOfContactId")
        has_dm = poc_id is not None and poc_id in poc_set

        contexts.append(
            OpportunityContext(
                id=opp_id,
                name=opp["name"],
                amount=_extract_amount(opp.get("amount")),
                stage=opp.get("stage", "Unknown"),
                owner_email=owner_email,
                owner_name=owner_info.get("name"),
                company_name=company_map.get(opp.get("companyId", ""), None),
                close_date=_parse_date(opp.get("closeDate")),
                last_activity_at=last_activity,
                days_in_stage=days_in_stage,
                days_since_last_activity=days_since_activity,
                has_decision_maker=has_dm,
            )
        )

    return contexts
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_normalizer.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/ingestion/normalizer.py tests/test_normalizer.py
git commit -m "feat: normalizer — map Twenty GraphQL responses to OpportunityContext"
```

---

## Task 6: Rule Engine

**Files:**
- Create: `pipeline_coach/hygiene/rules.py`
- Create: `tests/test_rules.py`

- [ ] **Step 1: Write tests for rule evaluation**

```python
# tests/test_rules.py
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from pipeline_coach.config import load_rules_config
from pipeline_coach.hygiene.rules import evaluate_opportunity
from pipeline_coach.models import Issue, OpportunityContext


@pytest.fixture()
def rules_config(tmp_path: Path):
    content = """\
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
    p = tmp_path / "rules.yaml"
    p.write_text(content)
    return load_rules_config(p)


class TestStaleInStage:
    def test_stale_with_stage_override(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Negotiation", owner_email="a@b.com",
            days_in_stage=10,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        stale = [i for i in issues if i.rule_id == "stale_in_stage"]
        assert len(stale) == 1
        assert stale[0].details["threshold"] == 7

    def test_not_stale_under_threshold(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Negotiation", owner_email="a@b.com",
            days_in_stage=5,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert not [i for i in issues if i.rule_id == "stale_in_stage"]

    def test_stale_uses_default_for_unknown_stage(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Discovery", owner_email="a@b.com",
            days_in_stage=15,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        stale = [i for i in issues if i.rule_id == "stale_in_stage"]
        assert len(stale) == 1
        assert stale[0].details["threshold"] == 14


class TestNoRecentActivity:
    def test_no_activity_fires(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            days_since_last_activity=10,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert any(i.rule_id == "no_recent_activity" for i in issues)

    def test_recent_activity_passes(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            days_since_last_activity=3,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert not any(i.rule_id == "no_recent_activity" for i in issues)

    def test_null_activity_skipped(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            days_since_last_activity=None,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert not any(i.rule_id == "no_recent_activity" for i in issues)


class TestCloseDatePast:
    def test_past_close_date_fires(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Negotiation", owner_email="a@b.com",
            close_date=date(2026, 3, 15),
        )
        issues = evaluate_opportunity(ctx, rules_config, today=date(2026, 3, 30))
        assert any(i.rule_id == "close_date_past" for i in issues)

    def test_future_close_date_passes(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Negotiation", owner_email="a@b.com",
            close_date=date(2026, 5, 1),
        )
        issues = evaluate_opportunity(ctx, rules_config, today=date(2026, 3, 30))
        assert not any(i.rule_id == "close_date_past" for i in issues)


class TestCloseDateSoonNoActivity:
    def test_soon_and_no_activity_fires(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            close_date=date(2026, 4, 3), days_since_last_activity=10,
        )
        issues = evaluate_opportunity(ctx, rules_config, today=date(2026, 3, 30))
        assert any(i.rule_id == "close_date_soon_no_activity" for i in issues)

    def test_soon_but_recent_activity_passes(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            close_date=date(2026, 4, 3), days_since_last_activity=3,
        )
        issues = evaluate_opportunity(ctx, rules_config, today=date(2026, 3, 30))
        assert not any(i.rule_id == "close_date_soon_no_activity" for i in issues)


class TestMissingFields:
    def test_missing_amount(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            amount=None,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert any(i.rule_id == "missing_amount" for i in issues)

    def test_zero_amount(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            amount=0.0,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert any(i.rule_id == "missing_amount" for i in issues)

    def test_missing_close_date(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            close_date=None,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert any(i.rule_id == "missing_close_date" for i in issues)

    def test_missing_decision_maker_in_relevant_stage(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            has_decision_maker=False,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert any(i.rule_id == "missing_decision_maker" for i in issues)

    def test_missing_decision_maker_in_irrelevant_stage(self, rules_config) -> None:
        ctx = OpportunityContext(
            id="1", name="Deal", stage="Qualification", owner_email="a@b.com",
            has_decision_maker=False,
        )
        issues = evaluate_opportunity(ctx, rules_config)
        assert not any(i.rule_id == "missing_decision_maker" for i in issues)


class TestCleanOppNoIssues:
    def test_clean_opp_returns_empty(self, rules_config, sample_opp_context_clean) -> None:
        issues = evaluate_opportunity(sample_opp_context_clean, rules_config, today=date(2026, 3, 30))
        assert issues == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_rules.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement rules.py**

```python
# pipeline_coach/hygiene/rules.py
from __future__ import annotations

from datetime import date

from pipeline_coach.config import RulesConfig
from pipeline_coach.models import Issue, OpportunityContext


def evaluate_opportunity(
    ctx: OpportunityContext,
    rules_config: RulesConfig,
    *,
    today: date | None = None,
) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    # Stale in stage
    cfg = rules_config.stale_in_stage
    if cfg.enabled and ctx.days_in_stage is not None:
        threshold = cfg.by_stage.get(ctx.stage, cfg.default_days)
        if ctx.days_in_stage > threshold:
            issues.append(Issue(
                rule_id="stale_in_stage",
                severity=cfg.severity,
                message=f"Stale in {ctx.stage}: {ctx.days_in_stage} days (threshold: {threshold})",
                details={"stage": ctx.stage, "days": ctx.days_in_stage, "threshold": threshold},
            ))

    # No recent activity
    cfg_act = rules_config.no_recent_activity
    if cfg_act.enabled and ctx.days_since_last_activity is not None:
        if ctx.days_since_last_activity > cfg_act.days:
            issues.append(Issue(
                rule_id="no_recent_activity",
                severity=cfg_act.severity,
                message=(
                    f"No activity in {ctx.days_since_last_activity} days "
                    f"(threshold: {cfg_act.days})"
                ),
                details={
                    "days": ctx.days_since_last_activity,
                    "threshold": cfg_act.days,
                },
            ))

    # Close date in the past
    cfg_past = rules_config.close_date_past
    if cfg_past.enabled and ctx.close_date is not None:
        if ctx.close_date < today:
            issues.append(Issue(
                rule_id="close_date_past",
                severity=cfg_past.severity,
                message=f"Close date {ctx.close_date} is in the past",
                details={"close_date": str(ctx.close_date)},
            ))

    # Close date soon + no activity
    cfg_soon = rules_config.close_date_soon_no_activity
    if cfg_soon.enabled and ctx.close_date is not None:
        days_until_close = (ctx.close_date - today).days
        if (
            0 <= days_until_close <= cfg_soon.close_date_soon_days
            and ctx.days_since_last_activity is not None
            and ctx.days_since_last_activity > cfg_soon.no_activity_days
        ):
            issues.append(Issue(
                rule_id="close_date_soon_no_activity",
                severity=cfg_soon.severity,
                message=(
                    f"Close date in {days_until_close} days with no activity "
                    f"in {ctx.days_since_last_activity} days"
                ),
                details={
                    "days_until_close": days_until_close,
                    "days_since_activity": ctx.days_since_last_activity,
                },
            ))

    # Missing amount
    cfg_amt = rules_config.missing_amount
    if cfg_amt.enabled and (ctx.amount is None or ctx.amount == 0.0):
        issues.append(Issue(
            rule_id="missing_amount",
            severity=cfg_amt.severity,
            message="Deal amount is missing or zero",
        ))

    # Missing close date
    cfg_cd = rules_config.missing_close_date
    if cfg_cd.enabled and ctx.close_date is None:
        issues.append(Issue(
            rule_id="missing_close_date",
            severity=cfg_cd.severity,
            message="Close date is not set",
        ))

    # Missing decision maker (stage-specific)
    cfg_dm = rules_config.missing_decision_maker
    if cfg_dm.enabled and ctx.stage in cfg_dm.by_stage:
        if ctx.has_decision_maker is False:
            issues.append(Issue(
                rule_id="missing_decision_maker",
                severity=cfg_dm.severity,
                message=f"No decision maker identified (required for {ctx.stage})",
                details={"stage": ctx.stage},
            ))

    return issues
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_rules.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/hygiene/rules.py tests/test_rules.py
git commit -m "feat: YAML-driven hygiene rule engine with per-stage thresholds"
```

---

## Task 7: Priority Scoring

**Files:**
- Create: `pipeline_coach/hygiene/priority.py`
- Create: `tests/test_priority.py`

- [ ] **Step 1: Write tests for priority scoring**

```python
# tests/test_priority.py
from __future__ import annotations

import pytest

from pipeline_coach.hygiene.priority import compute_priority
from pipeline_coach.models import Issue


class TestComputePriority:
    def test_high_severity_issue_yields_high(self) -> None:
        issues = [
            Issue(rule_id="close_date_past", severity="high", message="past"),
        ]
        assert compute_priority(issues, amount=50_000.0, stage="Negotiation") == "high"

    def test_medium_severity_only(self) -> None:
        issues = [
            Issue(rule_id="stale_in_stage", severity="medium", message="stale"),
        ]
        assert compute_priority(issues, amount=10_000.0, stage="Qualification") == "medium"

    def test_low_severity_only(self) -> None:
        issues = [
            Issue(rule_id="missing_decision_maker", severity="low", message="no dm"),
        ]
        assert compute_priority(issues, amount=5_000.0, stage="Discovery") == "low"

    def test_worst_issue_wins(self) -> None:
        issues = [
            Issue(rule_id="stale_in_stage", severity="low", message="stale"),
            Issue(rule_id="close_date_past", severity="high", message="past"),
        ]
        assert compute_priority(issues, amount=10_000.0, stage="Qualification") == "high"

    def test_empty_issues_returns_low(self) -> None:
        assert compute_priority([], amount=100_000.0, stage="Negotiation") == "low"

    def test_large_amount_late_stage_medium_issue_stays_medium(self) -> None:
        issues = [
            Issue(rule_id="no_recent_activity", severity="medium", message="no activity"),
        ]
        assert compute_priority(issues, amount=200_000.0, stage="Negotiation") == "medium"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_priority.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement priority.py**

```python
# pipeline_coach/hygiene/priority.py
from __future__ import annotations

from typing import Literal

from pipeline_coach.models import Issue

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def compute_priority(
    issues: list[Issue],
    amount: float | None = None,
    stage: str | None = None,
) -> Literal["high", "medium", "low"]:
    if not issues:
        return "low"

    worst = max(issues, key=lambda i: SEVERITY_RANK[i.severity])
    return worst.severity
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_priority.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/hygiene/priority.py tests/test_priority.py
git commit -m "feat: priority scoring — worst-issue-wins heuristic"
```

---

## Task 8: DSPy Actions Module

**Files:**
- Create: `pipeline_coach/coach/actions.py`
- Create: `tests/test_actions.py`

- [ ] **Step 1: Write tests for action generation**

```python
# tests/test_actions.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline_coach.coach.actions import (
    FALLBACK_ACTIONS,
    generate_suggested_action,
)
from pipeline_coach.models import Issue, OpportunityContext


class TestFallbackActions:
    def test_fallback_for_close_date_past(self) -> None:
        issues = [Issue(rule_id="close_date_past", severity="high", message="past")]
        result = generate_suggested_action(
            ctx=OpportunityContext(
                id="1", name="Deal", stage="Negotiation", owner_email="a@b.com",
                close_date=None,
            ),
            issues=issues,
            use_llm=False,
        )
        assert "close date" in result.lower()

    def test_fallback_for_stale_in_stage(self) -> None:
        issues = [
            Issue(
                rule_id="stale_in_stage", severity="medium", message="stale",
                details={"stage": "Proposal", "days": 20},
            )
        ]
        result = generate_suggested_action(
            ctx=OpportunityContext(
                id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
            ),
            issues=issues,
            use_llm=False,
        )
        assert "Proposal" in result
        assert "20" in result

    def test_fallback_uses_highest_severity_rule(self) -> None:
        issues = [
            Issue(rule_id="missing_amount", severity="medium", message="missing"),
            Issue(rule_id="close_date_past", severity="high", message="past"),
        ]
        result = generate_suggested_action(
            ctx=OpportunityContext(
                id="1", name="Deal", stage="Negotiation", owner_email="a@b.com",
            ),
            issues=issues,
            use_llm=False,
        )
        assert "close date" in result.lower()

    def test_empty_issues_returns_none(self) -> None:
        result = generate_suggested_action(
            ctx=OpportunityContext(
                id="1", name="Deal", stage="Discovery", owner_email="a@b.com",
            ),
            issues=[],
            use_llm=False,
        )
        assert result is None

    def test_llm_path_called_when_enabled(self) -> None:
        issues = [Issue(rule_id="stale_in_stage", severity="medium", message="stale")]
        mock_prediction = MagicMock()
        mock_prediction.suggested_action = "Call the client to check in on the deal."

        with patch("pipeline_coach.coach.actions._predict_action") as mock_predict:
            mock_predict.return_value = mock_prediction
            result = generate_suggested_action(
                ctx=OpportunityContext(
                    id="1", name="Deal", stage="Proposal", owner_email="a@b.com",
                ),
                issues=issues,
                use_llm=True,
            )
            assert result == "Call the client to check in on the deal."
            mock_predict.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_actions.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement actions.py**

```python
# pipeline_coach/coach/actions.py
from __future__ import annotations

import dspy
import structlog

from pipeline_coach.models import Issue, OpportunityContext

logger = structlog.get_logger()

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

FALLBACK_ACTIONS: dict[str, str] = {
    "stale_in_stage": (
        "Review this deal — it's been in {stage} for {days} days. "
        "Update the stage or add a next step."
    ),
    "no_recent_activity": "Log your latest interaction or schedule a follow-up.",
    "close_date_past": "Update the close date — the current one has passed.",
    "close_date_soon_no_activity": (
        "Close date is in {days_until_close} days with no recent activity. "
        "Confirm timing or push the date."
    ),
    "missing_amount": "Add a deal amount so forecasting is accurate.",
    "missing_close_date": "Set a close date for this opportunity.",
    "missing_decision_maker": "Identify and add a decision maker contact.",
}


class SuggestActionSig(dspy.Signature):
    """Given an opportunity summary and its hygiene issues, propose one concise, practical next action for the AE."""

    opportunity_summary: str = dspy.InputField()
    issues: str = dspy.InputField()
    suggested_action: str = dspy.OutputField(
        desc="One concise, practical next best action for the AE. Be specific — name the action, not the problem."
    )


_predictor = dspy.Predict(SuggestActionSig)


def _predict_action(summary: str, issues_text: str) -> dspy.Prediction:
    return _predictor(opportunity_summary=summary, issues=issues_text)


def _render_summary(ctx: OpportunityContext) -> str:
    parts = [f"{ctx.name} — Stage: {ctx.stage}"]
    if ctx.amount is not None:
        parts.append(f"Amount: ${ctx.amount:,.0f}")
    if ctx.company_name:
        parts.append(f"Company: {ctx.company_name}")
    if ctx.close_date:
        parts.append(f"Close date: {ctx.close_date}")
    if ctx.last_activity_at:
        parts.append(f"Last activity: {ctx.last_activity_at.date()}")
    return " | ".join(parts)


def _get_fallback(issues: list[Issue]) -> str | None:
    if not issues:
        return None
    worst = max(issues, key=lambda i: SEVERITY_RANK[i.severity])
    template = FALLBACK_ACTIONS.get(worst.rule_id)
    if not template:
        return f"Review this deal — {worst.message}"
    try:
        return template.format(**worst.details)
    except KeyError:
        return template.split("{")[0].rstrip(" —")


def generate_suggested_action(
    *,
    ctx: OpportunityContext,
    issues: list[Issue],
    use_llm: bool = False,
) -> str | None:
    if not issues:
        return None

    if not use_llm:
        return _get_fallback(issues)

    summary = _render_summary(ctx)
    issues_text = "\n".join(f"- {i.message}" for i in issues)

    try:
        prediction = _predict_action(summary, issues_text)
        action = prediction.suggested_action
        if action and action.strip():
            return action.strip()
    except Exception:
        logger.warning("dspy_predict_failed", opp_id=ctx.id, exc_info=True)

    return _get_fallback(issues)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_actions.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/coach/actions.py tests/test_actions.py
git commit -m "feat: DSPy action suggestions with deterministic fallback"
```

---

## Task 9: Quality Gate

**Files:**
- Create: `pipeline_coach/coach/quality_gate.py`
- Create: `tests/test_quality_gate.py`

- [ ] **Step 1: Write tests for the quality gate**

```python
# tests/test_quality_gate.py
from __future__ import annotations

import pytest

from pipeline_coach.coach.quality_gate import validate_action


class TestValidateAction:
    def test_valid_action_passes(self) -> None:
        assert validate_action(
            "Schedule a call with the Acme team to confirm the timeline.",
            issues_text="Close date has passed",
        ) is True

    def test_empty_action_fails(self) -> None:
        assert validate_action("", issues_text="some issue") is False

    def test_whitespace_only_fails(self) -> None:
        assert validate_action("   \n  ", issues_text="some issue") is False

    def test_none_action_fails(self) -> None:
        assert validate_action(None, issues_text="some issue") is False

    def test_restatement_of_issue_fails(self) -> None:
        assert validate_action(
            "Close date has passed",
            issues_text="Close date has passed",
        ) is False

    def test_similar_restatement_fails(self) -> None:
        assert validate_action(
            "The close date has passed.",
            issues_text="Close date has passed",
        ) is False

    def test_action_with_verb_passes(self) -> None:
        assert validate_action(
            "Update the close date to next quarter.",
            issues_text="Close date has passed",
        ) is True

    def test_no_verb_noun_only_fails(self) -> None:
        assert validate_action(
            "The deal amount.",
            issues_text="Amount is missing",
        ) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_quality_gate.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement quality_gate.py**

```python
# pipeline_coach/coach/quality_gate.py
from __future__ import annotations

# Common action verbs expected in suggested actions
_ACTION_VERBS = {
    "schedule", "call", "email", "update", "set", "add", "review", "confirm",
    "check", "follow", "send", "ask", "reach", "arrange", "book", "create",
    "discuss", "escalate", "identify", "log", "move", "push", "remove",
    "request", "share", "verify", "contact", "prioritize",
}


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _is_restatement(action: str, issues_text: str) -> bool:
    norm_action = _normalize(action)
    for line in issues_text.split("\n"):
        norm_line = _normalize(line.lstrip("- "))
        if not norm_line:
            continue
        # Check if action is essentially the same as an issue line
        if norm_action == norm_line:
            return True
        # Check high overlap: if >80% of words match
        action_words = set(norm_action.split())
        issue_words = set(norm_line.split())
        if not action_words:
            continue
        overlap = len(action_words & issue_words) / len(action_words)
        if overlap > 0.8:
            return True
    return False


def _has_action_verb(action: str) -> bool:
    words = _normalize(action).split()
    # Check first 3 words for an action verb
    for word in words[:3]:
        if word.rstrip(".,!?") in _ACTION_VERBS:
            return True
    return False


def validate_action(action: str | None, *, issues_text: str) -> bool:
    if not action or not action.strip():
        return False

    stripped = action.strip()

    if _is_restatement(stripped, issues_text):
        return False

    if not _has_action_verb(stripped):
        return False

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_quality_gate.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/coach/quality_gate.py tests/test_quality_gate.py
git commit -m "feat: quality gate — validate LLM actions for actionability and originality"
```

---

## Task 10: Brief Rendering

**Files:**
- Create: `pipeline_coach/coach/brief.py`
- Create: `tests/test_brief.py`

- [ ] **Step 1: Write tests for brief rendering**

```python
# tests/test_brief.py
from __future__ import annotations

from datetime import date

import pytest

from pipeline_coach.coach.brief import render_ae_brief, render_escalation_brief
from pipeline_coach.models import Issue, IssueSummary, OpportunityContext


@pytest.fixture()
def summaries() -> list[IssueSummary]:
    ctx1 = OpportunityContext(
        id="opp-1", name="Acme Expansion", amount=120_000.0,
        stage="Negotiation", owner_email="alex@demo.com", owner_name="Alex Doe",
        company_name="Acme Corp", close_date=date(2026, 3, 15),
        days_since_last_activity=18,
    )
    ctx2 = OpportunityContext(
        id="opp-2", name="Northwind Upsell", amount=30_000.0,
        stage="Proposal", owner_email="alex@demo.com", owner_name="Alex Doe",
        company_name="Northwind",
    )
    return [
        IssueSummary(
            opportunity_id="opp-1", opportunity_name="Acme Expansion",
            owner_email="alex@demo.com", priority="high",
            issues=[
                Issue(rule_id="close_date_past", severity="high",
                      message="Close date 2026-03-15 is in the past"),
                Issue(rule_id="no_recent_activity", severity="medium",
                      message="No activity in 18 days (threshold: 7)"),
            ],
            context=ctx1,
            suggested_action="Schedule a call with Acme to confirm the deal timeline.",
        ),
        IssueSummary(
            opportunity_id="opp-2", opportunity_name="Northwind Upsell",
            owner_email="alex@demo.com", priority="medium",
            issues=[
                Issue(rule_id="missing_close_date", severity="medium",
                      message="Close date is not set"),
            ],
            context=ctx2,
            suggested_action="Set a close date for this opportunity.",
        ),
    ]


class TestRenderAeBrief:
    def test_contains_greeting(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert "Hi Alex" in text

    def test_contains_date(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert "2026-03-30" in text

    def test_contains_opp_names(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert "Acme Expansion" in text
        assert "Northwind Upsell" in text

    def test_contains_issues(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert "Close date 2026-03-15 is in the past" in text

    def test_contains_suggested_action(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert "Schedule a call with Acme" in text

    def test_contains_amount(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert "$120,000" in text

    def test_subject_line(self, summaries: list[IssueSummary]) -> None:
        text = render_ae_brief("Alex Doe", summaries, today=date(2026, 3, 30))
        assert text.startswith("Subject: Your Pipeline Coach brief for 2026-03-30")


class TestRenderEscalationBrief:
    def test_contains_escalation_marker(self, summaries: list[IssueSummary]) -> None:
        text = render_escalation_brief(
            manager_name="Sales VP",
            ae_name="Alex Doe",
            ae_email="alex@demo.com",
            summaries=[summaries[0]],
            today=date(2026, 3, 30),
        )
        assert "[Escalation]" in text

    def test_contains_ae_info(self, summaries: list[IssueSummary]) -> None:
        text = render_escalation_brief(
            manager_name="Sales VP",
            ae_name="Alex Doe",
            ae_email="alex@demo.com",
            summaries=[summaries[0]],
            today=date(2026, 3, 30),
        )
        assert "Alex Doe" in text
        assert "alex@demo.com" in text

    def test_contains_deal_info(self, summaries: list[IssueSummary]) -> None:
        text = render_escalation_brief(
            manager_name="Sales VP",
            ae_name="Alex Doe",
            ae_email="alex@demo.com",
            summaries=[summaries[0]],
            today=date(2026, 3, 30),
        )
        assert "Acme Expansion" in text
        assert "$120,000" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_brief.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement brief.py**

```python
# pipeline_coach/coach/brief.py
from __future__ import annotations

from datetime import date

from pipeline_coach.models import IssueSummary


def _format_amount(amount: float | None) -> str:
    if amount is None:
        return "Not set"
    return f"${amount:,.0f}"


def _format_date(d: date | None, today: date) -> str:
    if d is None:
        return "Not set"
    label = str(d)
    if d < today:
        label += " (PAST)"
    return label


def _render_opp_entry(idx: int, s: IssueSummary, today: date) -> str:
    ctx = s.context
    lines = [
        f"{idx}) {s.opportunity_name} — {_format_amount(ctx.amount)} — Stage: {ctx.stage}",
    ]
    if ctx.company_name:
        lines.append(f"   Company: {ctx.company_name}")
    if ctx.days_since_last_activity is not None:
        lines.append(f"   Last activity: {ctx.days_since_last_activity} days ago")
    else:
        lines.append("   Last activity: No activity recorded")
    lines.append(f"   Close date: {_format_date(ctx.close_date, today)}")
    lines.append("   Issues:")
    for issue in s.issues:
        lines.append(f"     - {issue.message}")
    if s.suggested_action:
        lines.append(f"   Suggested action: {s.suggested_action}")
    return "\n".join(lines)


def render_ae_brief(
    owner_name: str | None,
    summaries: list[IssueSummary],
    *,
    today: date | None = None,
) -> str:
    today = today or date.today()
    greeting_name = (owner_name or "there").split()[0]
    n = len(summaries)

    lines = [
        f"Subject: Your Pipeline Coach brief for {today}",
        "",
        f"Hi {greeting_name},",
        "",
        f"Here are your top {n} pipeline actions for today:",
        "",
    ]

    for idx, s in enumerate(summaries, 1):
        lines.append(_render_opp_entry(idx, s, today))
        lines.append("")

    lines.append("Best,")
    lines.append("Pipeline Coach")
    return "\n".join(lines)


def render_escalation_brief(
    *,
    manager_name: str | None,
    ae_name: str,
    ae_email: str,
    summaries: list[IssueSummary],
    today: date | None = None,
) -> str:
    today = today or date.today()
    n = len(summaries)
    greeting = (manager_name or "Manager").split()[0]

    lines = [
        f"Subject: [Escalation] {n} critical deal{'s' if n != 1 else ''} need attention — {today}",
        "",
        f"Hi {greeting},",
        "",
        f"The following deal{'s' if n != 1 else ''} owned by {ae_name} {'are' if n != 1 else 'is'} flagged as critical:",
        "",
    ]

    for idx, s in enumerate(summaries, 1):
        ctx = s.context
        lines.append(
            f"{idx}) {s.opportunity_name} — {_format_amount(ctx.amount)} — Stage: {ctx.stage}"
        )
        lines.append("   Issues:")
        for issue in s.issues:
            lines.append(f"     - {issue.message}")
        lines.append(f"   AE: {ae_name} ({ae_email})")
        lines.append("")

    lines.append(f"Please follow up with {ae_name.split()[0]} on {'these deals' if n != 1 else 'this deal'}.")
    lines.append("")
    lines.append("Best,")
    lines.append("Pipeline Coach")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_brief.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/coach/brief.py tests/test_brief.py
git commit -m "feat: brief rendering — AE daily brief and manager escalation text"
```

---

## Task 11: Email Client (Resend)

**Files:**
- Create: `pipeline_coach/delivery/email_client.py`
- Create: `tests/test_email_client.py`

- [ ] **Step 1: Write tests for the email client**

```python
# tests/test_email_client.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline_coach.delivery.email_client import ResendClient


class TestResendClient:
    def test_send_calls_resend_api(self) -> None:
        with patch("pipeline_coach.delivery.email_client.resend") as mock_resend:
            mock_resend.Emails.send.return_value = {"id": "email-123"}
            client = ResendClient(api_key="re_test", from_email="coach@test.com")
            result = client.send(
                to="alex@demo.com",
                subject="Test brief",
                body="Hello",
            )
            assert result == "email-123"
            mock_resend.Emails.send.assert_called_once()
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert call_args["to"] == ["alex@demo.com"]
            assert call_args["subject"] == "Test brief"
            assert call_args["text"] == "Hello"
            assert call_args["from"] == "coach@test.com"

    def test_send_returns_none_on_error(self) -> None:
        with patch("pipeline_coach.delivery.email_client.resend") as mock_resend:
            mock_resend.Emails.send.side_effect = Exception("API error")
            client = ResendClient(api_key="re_test", from_email="coach@test.com")
            result = client.send(
                to="alex@demo.com",
                subject="Test",
                body="Hello",
            )
            assert result is None

    def test_sets_api_key_on_init(self) -> None:
        with patch("pipeline_coach.delivery.email_client.resend") as mock_resend:
            ResendClient(api_key="re_my_key", from_email="coach@test.com")
            assert mock_resend.api_key == "re_my_key"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_email_client.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement email_client.py**

```python
# pipeline_coach/delivery/email_client.py
from __future__ import annotations

import resend
import structlog

logger = structlog.get_logger()


class ResendClient:
    def __init__(self, api_key: str, from_email: str) -> None:
        resend.api_key = api_key
        self._from_email = from_email

    def send(self, *, to: str, subject: str, body: str) -> str | None:
        params: resend.Emails.SendParams = {
            "from": self._from_email,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        try:
            response = resend.Emails.send(params)
            email_id = response["id"]
            logger.info("email_sent", to=to, subject=subject, email_id=email_id)
            return email_id
        except Exception:
            logger.error("email_send_failed", to=to, subject=subject, exc_info=True)
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_email_client.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/delivery/email_client.py tests/test_email_client.py
git commit -m "feat: Resend email client wrapper"
```

---

## Task 12: Escalation Router

**Files:**
- Create: `pipeline_coach/delivery/router.py`
- Create: `tests/test_router.py`

- [ ] **Step 1: Write tests for routing logic**

```python
# tests/test_router.py
from __future__ import annotations

from datetime import date

import pytest

from pipeline_coach.config import EscalationConfig
from pipeline_coach.delivery.router import route_summaries, RoutingResult
from pipeline_coach.models import Issue, IssueSummary, OpportunityContext


@pytest.fixture()
def escalation_config() -> EscalationConfig:
    return EscalationConfig(
        default_manager="vp@demo.com",
        overrides={"alex@demo.com": "mgr-a@demo.com"},
        critical_amount_threshold=50_000.0,
    )


@pytest.fixture()
def high_value_summary() -> IssueSummary:
    return IssueSummary(
        opportunity_id="opp-1", opportunity_name="Big Deal",
        owner_email="alex@demo.com", priority="high",
        issues=[Issue(rule_id="close_date_past", severity="high", message="past")],
        context=OpportunityContext(
            id="opp-1", name="Big Deal", amount=120_000.0,
            stage="Negotiation", owner_email="alex@demo.com",
            owner_name="Alex Doe",
        ),
        suggested_action="Update close date.",
    )


@pytest.fixture()
def low_value_summary() -> IssueSummary:
    return IssueSummary(
        opportunity_id="opp-2", opportunity_name="Small Deal",
        owner_email="alex@demo.com", priority="medium",
        issues=[Issue(rule_id="stale_in_stage", severity="medium", message="stale")],
        context=OpportunityContext(
            id="opp-2", name="Small Deal", amount=10_000.0,
            stage="Discovery", owner_email="alex@demo.com",
            owner_name="Alex Doe",
        ),
        suggested_action="Follow up.",
    )


class TestRouteSummaries:
    def test_critical_deal_generates_escalation(
        self, escalation_config: EscalationConfig, high_value_summary: IssueSummary
    ) -> None:
        result = route_summaries([high_value_summary], escalation_config)
        assert "alex@demo.com" in result.ae_briefs
        assert "mgr-a@demo.com" in result.escalations

    def test_non_critical_no_escalation(
        self, escalation_config: EscalationConfig, low_value_summary: IssueSummary
    ) -> None:
        result = route_summaries([low_value_summary], escalation_config)
        assert "alex@demo.com" in result.ae_briefs
        assert len(result.escalations) == 0

    def test_unknown_ae_uses_default_manager(
        self, escalation_config: EscalationConfig
    ) -> None:
        summary = IssueSummary(
            opportunity_id="opp-3", opportunity_name="Unknown AE Deal",
            owner_email="unknown@demo.com", priority="high",
            issues=[Issue(rule_id="close_date_past", severity="high", message="past")],
            context=OpportunityContext(
                id="opp-3", name="Unknown AE Deal", amount=100_000.0,
                stage="Negotiation", owner_email="unknown@demo.com",
            ),
        )
        result = route_summaries([summary], escalation_config)
        assert "vp@demo.com" in result.escalations

    def test_high_priority_but_low_amount_no_escalation(
        self, escalation_config: EscalationConfig
    ) -> None:
        summary = IssueSummary(
            opportunity_id="opp-4", opportunity_name="High Pri Low Amount",
            owner_email="alex@demo.com", priority="high",
            issues=[Issue(rule_id="close_date_past", severity="high", message="past")],
            context=OpportunityContext(
                id="opp-4", name="High Pri Low Amount", amount=5_000.0,
                stage="Proposal", owner_email="alex@demo.com",
            ),
        )
        result = route_summaries([summary], escalation_config)
        assert len(result.escalations) == 0

    def test_multiple_aes_grouped(self, escalation_config: EscalationConfig) -> None:
        s1 = IssueSummary(
            opportunity_id="opp-a", opportunity_name="Deal A",
            owner_email="alex@demo.com", priority="medium",
            issues=[Issue(rule_id="stale_in_stage", severity="medium", message="stale")],
            context=OpportunityContext(
                id="opp-a", name="Deal A", amount=20_000.0,
                stage="Discovery", owner_email="alex@demo.com", owner_name="Alex Doe",
            ),
        )
        s2 = IssueSummary(
            opportunity_id="opp-b", opportunity_name="Deal B",
            owner_email="jordan@demo.com", priority="medium",
            issues=[Issue(rule_id="missing_amount", severity="medium", message="missing")],
            context=OpportunityContext(
                id="opp-b", name="Deal B", stage="Qualification",
                owner_email="jordan@demo.com", owner_name="Jordan Lee",
            ),
        )
        result = route_summaries([s1, s2], escalation_config)
        assert "alex@demo.com" in result.ae_briefs
        assert "jordan@demo.com" in result.ae_briefs
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement router.py**

```python
# pipeline_coach/delivery/router.py
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pipeline_coach.config import EscalationConfig
from pipeline_coach.models import IssueSummary


@dataclass
class RoutingResult:
    ae_briefs: dict[str, list[IssueSummary]] = field(default_factory=dict)
    escalations: dict[str, list[IssueSummary]] = field(default_factory=dict)


def _is_critical(summary: IssueSummary, threshold: float) -> bool:
    return (
        summary.priority == "high"
        and summary.context.amount is not None
        and summary.context.amount >= threshold
    )


def route_summaries(
    summaries: list[IssueSummary],
    escalation_config: EscalationConfig,
) -> RoutingResult:
    ae_groups: dict[str, list[IssueSummary]] = defaultdict(list)
    escalation_groups: dict[str, list[IssueSummary]] = defaultdict(list)

    for s in summaries:
        ae_groups[s.owner_email].append(s)

        if _is_critical(s, escalation_config.critical_amount_threshold):
            manager = escalation_config.get_manager(s.owner_email)
            escalation_groups[manager].append(s)

    return RoutingResult(
        ae_briefs=dict(ae_groups),
        escalations=dict(escalation_groups),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_router.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/delivery/router.py tests/test_router.py
git commit -m "feat: escalation router — group by AE, route critical deals to managers"
```

---

## Task 13: LangGraph Workflow

**Files:**
- Create: `pipeline_coach/workflow/state.py`
- Create: `pipeline_coach/workflow/graph.py`
- Create: `tests/test_workflow.py`

- [ ] **Step 1: Implement state.py**

```python
# pipeline_coach/workflow/state.py
from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from pipeline_coach.models import IssueSummary, OpportunityContext


class PipelineState(TypedDict):
    # Raw data from parallel fetches
    companies: list[dict]
    people: list[dict]
    opportunities: list[dict]
    tasks: list[dict]
    workspace_members: list[dict]
    # Normalized data
    contexts: list[OpportunityContext]
    # Issues + actions
    issue_summaries: list[IssueSummary]
    # Briefs
    ae_briefs: dict[str, str]          # owner_email → brief text
    escalation_briefs: dict[str, str]  # manager_email → escalation text
    # Quality gate
    action_retry_count_by_opp: dict[str, int]
    # Metadata
    run_id: str
    emails_sent: int
    emails_failed: int
    errors: Annotated[list[str], add]
```

- [ ] **Step 2: Write tests for the workflow graph**

```python
# tests/test_workflow.py
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline_coach.config import (
    EscalationConfig,
    RulesConfig,
    load_rules_config,
)
from pipeline_coach.workflow.graph import build_graph


@pytest.fixture()
def rules_config(tmp_path: Path) -> RulesConfig:
    content = """\
rules:
  stale_in_stage:
    enabled: true
    default_days: 14
    by_stage:
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
    severity: low
"""
    p = tmp_path / "rules.yaml"
    p.write_text(content)
    return load_rules_config(p)


@pytest.fixture()
def escalation_config() -> EscalationConfig:
    return EscalationConfig(
        default_manager="vp@demo.com",
        overrides={"alex@demo.com": "mgr-a@demo.com"},
        critical_amount_threshold=50_000.0,
    )


@pytest.fixture()
def mock_twenty_client() -> MagicMock:
    client = MagicMock()
    client.fetch_all.side_effect = lambda collection, fields: {
        "companies": [{"id": "c1", "name": "Acme Corp"}],
        "people": [
            {"id": "p1", "name": {"firstName": "Jane", "lastName": "Doe"},
             "emails": {"primaryEmail": "jane@acme.com"}, "companyId": "c1", "jobTitle": "CTO"},
        ],
        "opportunities": [
            {"id": "opp-1", "name": "Acme Expansion",
             "amount": {"amountMicros": 120_000_000_000, "currencyCode": "USD"},
             "stage": "Negotiation", "closeDate": "2026-03-15T00:00:00Z",
             "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-03-09T00:00:00Z",
             "companyId": "c1", "pointOfContactId": "p1", "ownerId": "m1"},
        ],
        "tasks": [
            {"id": "t1", "createdAt": "2026-03-12T10:00:00Z", "status": "DONE",
             "taskTargets": {"edges": [{"node": {"opportunityId": "opp-1"}}]}},
        ],
        "workspaceMembers": [
            {"id": "m1", "name": {"firstName": "Alex", "lastName": "Doe"},
             "userEmail": "alex@demo.com"},
        ],
    }[collection]
    return client


@pytest.fixture()
def mock_email_client() -> MagicMock:
    client = MagicMock()
    client.send.return_value = "email-id-123"
    return client


class TestWorkflowEndToEnd:
    def test_full_pipeline_produces_briefs(
        self,
        rules_config: RulesConfig,
        escalation_config: EscalationConfig,
        mock_twenty_client: MagicMock,
        mock_email_client: MagicMock,
    ) -> None:
        graph = build_graph(
            twenty_client=mock_twenty_client,
            email_client=mock_email_client,
            rules_config=rules_config,
            escalation_config=escalation_config,
            use_llm=False,
            today=date(2026, 3, 30),
        )
        result = graph.invoke({
            "companies": [], "people": [], "opportunities": [],
            "tasks": [], "workspace_members": [],
            "contexts": [], "issue_summaries": [],
            "ae_briefs": {}, "escalation_briefs": {},
            "action_retry_count_by_opp": {},
            "run_id": "test-run-1",
            "emails_sent": 0, "emails_failed": 0,
            "errors": [],
        })

        # Should have found issues on the Acme deal
        assert len(result["issue_summaries"]) > 0
        # Should have generated AE brief for alex
        assert "alex@demo.com" in result["ae_briefs"]
        # Should have sent emails
        assert mock_email_client.send.called

    def test_critical_deal_triggers_escalation(
        self,
        rules_config: RulesConfig,
        escalation_config: EscalationConfig,
        mock_twenty_client: MagicMock,
        mock_email_client: MagicMock,
    ) -> None:
        graph = build_graph(
            twenty_client=mock_twenty_client,
            email_client=mock_email_client,
            rules_config=rules_config,
            escalation_config=escalation_config,
            use_llm=False,
            today=date(2026, 3, 30),
        )
        result = graph.invoke({
            "companies": [], "people": [], "opportunities": [],
            "tasks": [], "workspace_members": [],
            "contexts": [], "issue_summaries": [],
            "ae_briefs": {}, "escalation_briefs": {},
            "action_retry_count_by_opp": {},
            "run_id": "test-run-2",
            "emails_sent": 0, "emails_failed": 0,
            "errors": [],
        })

        # Acme deal is $120k + high priority → should escalate to mgr-a
        assert "mgr-a@demo.com" in result["escalation_briefs"]
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_workflow.py -v
```

Expected: `ImportError` — `build_graph` not found

- [ ] **Step 4: Implement graph.py**

```python
# pipeline_coach/workflow/graph.py
from __future__ import annotations

from datetime import date

import structlog
from langgraph.graph import END, START, StateGraph

from pipeline_coach.coach.actions import generate_suggested_action
from pipeline_coach.coach.brief import render_ae_brief, render_escalation_brief
from pipeline_coach.coach.quality_gate import validate_action
from pipeline_coach.config import EscalationConfig, RulesConfig
from pipeline_coach.delivery.email_client import ResendClient
from pipeline_coach.delivery.router import route_summaries
from pipeline_coach.hygiene.priority import compute_priority
from pipeline_coach.hygiene.rules import evaluate_opportunity
from pipeline_coach.ingestion.normalizer import normalize_opportunities
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.models import IssueSummary
from pipeline_coach.workflow.state import PipelineState

logger = structlog.get_logger()

MAX_ACTION_RETRIES = 2


def build_graph(
    *,
    twenty_client: TwentyClient,
    email_client: ResendClient,
    rules_config: RulesConfig,
    escalation_config: EscalationConfig,
    use_llm: bool = False,
    today: date | None = None,
) -> StateGraph:
    today = today or date.today()

    # --- Node functions ---

    def fetch_companies(state: PipelineState) -> dict:
        try:
            data = twenty_client.fetch_all("companies", "{ id name }")
            return {"companies": data}
        except Exception as e:
            return {"companies": [], "errors": [f"fetch_companies failed: {e}"]}

    def fetch_people(state: PipelineState) -> dict:
        try:
            data = twenty_client.fetch_all(
                "people",
                "{ id name { firstName lastName } emails { primaryEmail } companyId jobTitle }",
            )
            return {"people": data}
        except Exception as e:
            return {"people": [], "errors": [f"fetch_people failed: {e}"]}

    def fetch_opportunities(state: PipelineState) -> dict:
        try:
            data = twenty_client.fetch_all(
                "opportunities",
                "{ id name amount { amountMicros currencyCode } stage closeDate "
                "createdAt updatedAt companyId pointOfContactId ownerId }",
            )
            return {"opportunities": data}
        except Exception as e:
            return {"opportunities": [], "errors": [f"fetch_opportunities failed: {e}"]}

    def fetch_tasks(state: PipelineState) -> dict:
        try:
            data = twenty_client.fetch_all(
                "tasks",
                "{ id createdAt status taskTargets { edges { node { opportunityId } } } }",
            )
            return {"tasks": data}
        except Exception as e:
            return {"tasks": [], "errors": [f"fetch_tasks failed: {e}"]}

    def fetch_workspace_members(state: PipelineState) -> dict:
        try:
            data = twenty_client.fetch_all(
                "workspaceMembers",
                "{ id name { firstName lastName } userEmail }",
            )
            return {"workspace_members": data}
        except Exception as e:
            return {"workspace_members": [], "errors": [f"fetch_workspace_members failed: {e}"]}

    def join_data(state: PipelineState) -> dict:
        contexts = normalize_opportunities(
            opportunities=state["opportunities"],
            companies=state["companies"],
            people=state["people"],
            workspace_members=state["workspace_members"],
            tasks=state["tasks"],
            today=today,
        )
        logger.info("join_data_complete", contexts_count=len(contexts))
        return {"contexts": contexts}

    def compute_issues(state: PipelineState) -> dict:
        summaries: list[IssueSummary] = []
        for ctx in state["contexts"]:
            issues = evaluate_opportunity(ctx, rules_config, today=today)
            if not issues:
                continue
            priority = compute_priority(issues, amount=ctx.amount, stage=ctx.stage)
            summaries.append(IssueSummary(
                opportunity_id=ctx.id,
                opportunity_name=ctx.name,
                owner_email=ctx.owner_email,
                priority=priority,
                issues=issues,
                context=ctx,
            ))
        logger.info("compute_issues_complete", issues_count=len(summaries))
        return {"issue_summaries": summaries}

    def generate_actions(state: PipelineState) -> dict:
        updated: list[IssueSummary] = []
        retry_counts = dict(state.get("action_retry_count_by_opp", {}))

        for s in state["issue_summaries"]:
            if s.suggested_action is not None:
                updated.append(s)
                continue

            action = generate_suggested_action(
                ctx=s.context, issues=s.issues, use_llm=use_llm,
            )
            updated.append(s.model_copy(update={"suggested_action": action}))
            if use_llm:
                retry_counts[s.opportunity_id] = retry_counts.get(s.opportunity_id, 0)

        return {
            "issue_summaries": updated,
            "action_retry_count_by_opp": retry_counts,
        }

    def validate_actions(state: PipelineState) -> dict:
        needs_retry: list[IssueSummary] = []
        valid: list[IssueSummary] = []
        retry_counts = dict(state.get("action_retry_count_by_opp", {}))

        for s in state["issue_summaries"]:
            issues_text = "\n".join(f"- {i.message}" for i in s.issues)
            if validate_action(s.suggested_action, issues_text=issues_text):
                valid.append(s)
            else:
                count = retry_counts.get(s.opportunity_id, 0)
                if count < MAX_ACTION_RETRIES and use_llm:
                    retry_counts[s.opportunity_id] = count + 1
                    needs_retry.append(s.model_copy(update={"suggested_action": None}))
                else:
                    # Fallback to deterministic
                    fallback = generate_suggested_action(
                        ctx=s.context, issues=s.issues, use_llm=False,
                    )
                    valid.append(s.model_copy(update={"suggested_action": fallback}))

        all_summaries = valid + needs_retry
        return {
            "issue_summaries": all_summaries,
            "action_retry_count_by_opp": retry_counts,
        }

    def should_retry_actions(state: PipelineState) -> str:
        has_pending = any(
            s.suggested_action is None for s in state["issue_summaries"]
        )
        if has_pending:
            return "generate_actions"
        return "route_by_severity"

    def route_by_severity(state: PipelineState) -> dict:
        routing = route_summaries(state["issue_summaries"], escalation_config)

        ae_briefs: dict[str, str] = {}
        for owner_email, owner_summaries in routing.ae_briefs.items():
            sorted_summaries = sorted(
                owner_summaries,
                key=lambda s: ({"high": 0, "medium": 1, "low": 2}[s.priority], -(s.context.amount or 0)),
            )
            owner_name = sorted_summaries[0].context.owner_name
            ae_briefs[owner_email] = render_ae_brief(
                owner_name, sorted_summaries, today=today,
            )

        escalation_briefs: dict[str, str] = {}
        for manager_email, mgr_summaries in routing.escalations.items():
            by_ae: dict[str, list[IssueSummary]] = {}
            for s in mgr_summaries:
                by_ae.setdefault(s.owner_email, []).append(s)
            parts: list[str] = []
            for ae_email, ae_sums in by_ae.items():
                ae_name = ae_sums[0].context.owner_name or ae_email
                parts.append(render_escalation_brief(
                    manager_name=None,
                    ae_name=ae_name,
                    ae_email=ae_email,
                    summaries=ae_sums,
                    today=today,
                ))
            escalation_briefs[manager_email] = "\n\n---\n\n".join(parts)

        return {"ae_briefs": ae_briefs, "escalation_briefs": escalation_briefs}

    def send_emails(state: PipelineState) -> dict:
        sent = 0
        failed = 0

        for owner_email, brief_text in state["ae_briefs"].items():
            lines = brief_text.split("\n")
            subject = lines[0].replace("Subject: ", "") if lines else "Pipeline Coach Brief"
            body = "\n".join(lines[2:]) if len(lines) > 2 else brief_text
            result = email_client.send(to=owner_email, subject=subject, body=body)
            if result:
                sent += 1
            else:
                failed += 1

        for manager_email, esc_text in state["escalation_briefs"].items():
            lines = esc_text.split("\n")
            subject = lines[0].replace("Subject: ", "") if lines else "Pipeline Coach Escalation"
            body = "\n".join(lines[2:]) if len(lines) > 2 else esc_text
            result = email_client.send(to=manager_email, subject=subject, body=body)
            if result:
                sent += 1
            else:
                failed += 1

        logger.info("send_emails_complete", sent=sent, failed=failed)
        return {"emails_sent": sent, "emails_failed": failed}

    # --- Build graph ---

    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node("fetch_companies", fetch_companies)
    graph.add_node("fetch_people", fetch_people)
    graph.add_node("fetch_opportunities", fetch_opportunities)
    graph.add_node("fetch_tasks", fetch_tasks)
    graph.add_node("fetch_workspace_members", fetch_workspace_members)
    graph.add_node("join_data", join_data)
    graph.add_node("compute_issues", compute_issues)
    graph.add_node("generate_actions", generate_actions)
    graph.add_node("validate_actions", validate_actions)
    graph.add_node("route_by_severity", route_by_severity)
    graph.add_node("send_emails", send_emails)

    # Parallel fan-out from START
    graph.add_edge(START, "fetch_companies")
    graph.add_edge(START, "fetch_people")
    graph.add_edge(START, "fetch_opportunities")
    graph.add_edge(START, "fetch_tasks")
    graph.add_edge(START, "fetch_workspace_members")

    # Fan-in to join_data
    graph.add_edge("fetch_companies", "join_data")
    graph.add_edge("fetch_people", "join_data")
    graph.add_edge("fetch_opportunities", "join_data")
    graph.add_edge("fetch_tasks", "join_data")
    graph.add_edge("fetch_workspace_members", "join_data")

    # Linear pipeline
    graph.add_edge("join_data", "compute_issues")
    graph.add_edge("compute_issues", "generate_actions")
    graph.add_edge("generate_actions", "validate_actions")

    # Quality gate retry loop
    graph.add_conditional_edges(
        "validate_actions",
        should_retry_actions,
        {
            "generate_actions": "generate_actions",
            "route_by_severity": "route_by_severity",
        },
    )

    # Continue to send
    graph.add_edge("route_by_severity", "send_emails")
    graph.add_edge("send_emails", END)

    return graph.compile()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_workflow.py -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pipeline_coach/workflow/state.py pipeline_coach/workflow/graph.py tests/test_workflow.py
git commit -m "feat: LangGraph workflow — parallel fetch, quality gate loop, escalation routing"
```

---

## Task 14: Observability

**Files:**
- Create: `pipeline_coach/observability/logger.py`

- [ ] **Step 1: Implement structured logging and audit**

```python
# pipeline_coach/observability/logger.py
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog

from pipeline_coach.models import IssueSummary


def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if os.environ.get("LOG_FORMAT") != "json"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            int(os.environ.get("LOG_LEVEL", "20"))  # default INFO
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def write_audit_record(
    *,
    run_id: str,
    summaries: list[IssueSummary],
    emails_sent: int,
    emails_failed: int,
    redact_pii: bool = False,
    audit_dir: Path | None = None,
) -> None:
    audit_dir = audit_dir or Path("data")
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / "audit_log.jsonl"

    now = datetime.now(timezone.utc).isoformat()

    run_record = {
        "type": "run",
        "run_id": run_id,
        "timestamp": now,
        "opportunities_with_issues": len(summaries),
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
    }

    records = [run_record]

    for s in summaries:
        owner = s.owner_email if not redact_pii else "[REDACTED]"
        issue_record = {
            "type": "issue",
            "run_id": run_id,
            "timestamp": now,
            "opportunity_id": s.opportunity_id,
            "opportunity_name": s.opportunity_name,
            "owner_email": owner,
            "priority": s.priority,
            "rule_ids": [i.rule_id for i in s.issues],
            "suggested_action": s.suggested_action,
        }
        records.append(issue_record)

    with open(audit_file, "a") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
```

- [ ] **Step 2: Commit**

```bash
git add pipeline_coach/observability/logger.py
git commit -m "feat: structured logging and JSONL audit records"
```

---

## Task 15: Entry Points (run_once, scheduler, __main__)

**Files:**
- Create: `pipeline_coach/run_once.py`
- Create: `pipeline_coach/scheduler.py`
- Create: `pipeline_coach/__main__.py`

- [ ] **Step 1: Implement run_once.py**

```python
# pipeline_coach/run_once.py
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import structlog

from pipeline_coach.config import (
    AppConfig,
    load_app_config,
    load_escalation_config,
    load_rules_config,
)
from pipeline_coach.delivery.email_client import ResendClient
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.observability.logger import setup_logging, write_audit_record
from pipeline_coach.workflow.graph import build_graph

logger = structlog.get_logger()


def run_pipeline_once(
    *,
    config_dir: Path = Path("config"),
    app_config: AppConfig | None = None,
) -> dict:
    setup_logging()
    app_config = app_config or load_app_config()
    rules_config = load_rules_config(config_dir / "rules.yaml")
    escalation_config = load_escalation_config(config_dir / "escalation.yaml")

    twenty_client = TwentyClient(
        base_url=app_config.twenty_api_url,
        api_key=app_config.twenty_api_key,
    )
    email_client = ResendClient(
        api_key=app_config.resend_api_key,
        from_email=app_config.email_from,
    )

    run_id = str(uuid.uuid4())[:8]
    today = date.today()

    logger.info("pipeline_start", run_id=run_id, today=str(today))

    graph = build_graph(
        twenty_client=twenty_client,
        email_client=email_client,
        rules_config=rules_config,
        escalation_config=escalation_config,
        use_llm=app_config.llm_api_key is not None,
        today=today,
    )

    initial_state = {
        "companies": [],
        "people": [],
        "opportunities": [],
        "tasks": [],
        "workspace_members": [],
        "contexts": [],
        "issue_summaries": [],
        "ae_briefs": {},
        "escalation_briefs": {},
        "action_retry_count_by_opp": {},
        "run_id": run_id,
        "emails_sent": 0,
        "emails_failed": 0,
        "errors": [],
    }

    result = graph.invoke(initial_state)

    write_audit_record(
        run_id=run_id,
        summaries=result["issue_summaries"],
        emails_sent=result["emails_sent"],
        emails_failed=result["emails_failed"],
        redact_pii=app_config.audit_redact_pii,
    )

    logger.info(
        "pipeline_complete",
        run_id=run_id,
        issues=len(result["issue_summaries"]),
        emails_sent=result["emails_sent"],
        emails_failed=result["emails_failed"],
        errors=result["errors"],
    )

    twenty_client.close()
    return result
```

- [ ] **Step 2: Implement scheduler.py**

```python
# pipeline_coach/scheduler.py
from __future__ import annotations

from pathlib import Path

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline_coach.config import load_app_config
from pipeline_coach.observability.logger import setup_logging
from pipeline_coach.run_once import run_pipeline_once

logger = structlog.get_logger()


def start_scheduler(config_dir: Path = Path("config")) -> None:
    setup_logging()
    app_config = load_app_config()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline_once,
        CronTrigger(hour=app_config.run_at_hour, minute=0),
        kwargs={"config_dir": config_dir, "app_config": app_config},
        id="pipeline_coach_daily",
        name="Pipeline Coach Daily Run",
    )

    logger.info("scheduler_started", run_at_hour=app_config.run_at_hour)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler_stopped")
```

- [ ] **Step 3: Implement __main__.py**

```python
# pipeline_coach/__main__.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Pipeline Coach")
    parser.add_argument(
        "--once", action="store_true", help="Run the pipeline once and exit"
    )
    parser.add_argument(
        "--config-dir", type=Path, default=Path("config"),
        help="Path to config directory (default: config/)",
    )
    args = parser.parse_args()

    if args.once:
        from pipeline_coach.run_once import run_pipeline_once

        run_pipeline_once(config_dir=args.config_dir)
    else:
        from pipeline_coach.scheduler import start_scheduler

        start_scheduler(config_dir=args.config_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Commit**

```bash
git add pipeline_coach/run_once.py pipeline_coach/scheduler.py pipeline_coach/__main__.py
git commit -m "feat: entry points — run_once, APScheduler daily cron, CLI with --once flag"
```

---

## Task 16: show_recent CLI

**Files:**
- Create: `pipeline_coach/show_recent.py`

- [ ] **Step 1: Implement show_recent.py**

```python
# pipeline_coach/show_recent.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def show_recent(owner: str, audit_dir: Path = Path("data")) -> None:
    audit_file = audit_dir / "audit_log.jsonl"
    if not audit_file.exists():
        print(f"No audit log found at {audit_file}")
        sys.exit(1)

    # Find most recent run
    latest_run_id: str | None = None
    with open(audit_file) as f:
        for line in f:
            record = json.loads(line)
            if record["type"] == "run":
                latest_run_id = record["run_id"]

    if not latest_run_id:
        print("No runs found in audit log.")
        sys.exit(1)

    # Print run summary and issues for owner
    with open(audit_file) as f:
        for line in f:
            record = json.loads(line)
            if record.get("run_id") != latest_run_id:
                continue
            if record["type"] == "run":
                print(f"Run: {record['run_id']} at {record['timestamp']}")
                print(f"  Issues found: {record['opportunities_with_issues']}")
                print(f"  Emails sent: {record['emails_sent']}")
                print(f"  Emails failed: {record['emails_failed']}")
                print()
            elif record["type"] == "issue" and record.get("owner_email") == owner:
                print(f"  {record['opportunity_name']} [{record['priority']}]")
                print(f"    Rules: {', '.join(record['rule_ids'])}")
                if record.get("suggested_action"):
                    print(f"    Action: {record['suggested_action']}")
                print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Show recent Pipeline Coach audit")
    parser.add_argument("--owner", required=True, help="Owner email to filter by")
    parser.add_argument("--audit-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    show_recent(args.owner, args.audit_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add pipeline_coach/show_recent.py
git commit -m "feat: show_recent CLI — inspect recent brief/audit for an owner"
```

---

## Task 17: Seed Script

**Files:**
- Create: `scripts/seed_twenty.py`

- [ ] **Step 1: Implement seed script**

```python
# scripts/seed_twenty.py
"""Seed a Twenty CRM instance with sample pipeline data for Pipeline Coach demos."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline_coach.ingestion.twenty_client import TwentyClient

COMPANIES = ["Acme Corp", "Northwind", "GlobalSoft", "Brightwave", "NimbusHQ"]

AES = [
    {"firstName": "Alex", "lastName": "Doe", "email": "alex@demo.com"},
    {"firstName": "Jordan", "lastName": "Lee", "email": "jordan@demo.com"},
]

STAGES = ["Qualification", "Discovery", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]

CONTACTS = [
    ("Jane", "Smith", "jane@acme.com", 0),
    ("Bob", "Johnson", "bob@acme.com", 0),
    ("Sara", "Williams", "sara@northwind.com", 1),
    ("Mike", "Brown", "mike@northwind.com", 1),
    ("Lisa", "Davis", "lisa@globalsoft.com", 2),
    ("Tom", "Wilson", "tom@globalsoft.com", 2),
    ("Amy", "Taylor", "amy@brightwave.com", 3),
    ("Dan", "Anderson", "dan@brightwave.com", 3),
    ("Kim", "Thomas", "kim@nimbushq.com", 4),
    ("Pat", "Jackson", "pat@nimbushq.com", 4),
]


def _gql_mutation(client: TwentyClient, mutation: str) -> dict:
    """Run a raw GraphQL mutation."""
    return client._query(mutation)


def seed() -> None:
    base_url = os.environ["TWENTY_API_URL"]
    api_key = os.environ["TWENTY_API_KEY"]
    client = TwentyClient(base_url=base_url, api_key=api_key)

    now = datetime.now(timezone.utc)
    ids: dict[str, list[str]] = {"companies": [], "people": [], "opportunities": [], "tasks": []}

    # Create companies
    for name in COMPANIES:
        result = _gql_mutation(client, f'''
            mutation {{ createCompany(data: {{ name: "{name}" }}) {{ id }} }}
        ''')
        cid = result["createCompany"]["id"]
        ids["companies"].append(cid)
        print(f"  Company: {name} ({cid})")

    # Create contacts
    for first, last, email, comp_idx in CONTACTS:
        comp_id = ids["companies"][comp_idx]
        result = _gql_mutation(client, f'''
            mutation {{ createPerson(data: {{
                name: {{ firstName: "{first}", lastName: "{last}" }}
                emails: {{ primaryEmail: "{email}" }}
                companyId: "{comp_id}"
            }}) {{ id }} }}
        ''')
        pid = result["createPerson"]["id"]
        ids["people"].append(pid)

    # Create opportunities with varying hygiene issues
    opp_configs = [
        # (name, comp_idx, stage, amount_micros, close_days_offset, updated_days_ago, ae_idx, poc_idx)
        ("Acme Expansion", 0, "Negotiation", 120_000_000_000, -15, 21, 0, 0),
        ("Acme Renewal", 0, "Proposal", 45_000_000_000, 5, 3, 0, 1),
        ("Northwind Migration", 1, "Proposal", 80_000_000_000, -5, 28, 1, 2),
        ("Northwind Add-on", 1, "Discovery", 15_000_000_000, 30, 5, 1, 3),
        ("GlobalSoft Platform", 2, "Negotiation", 200_000_000_000, 3, 14, 0, 4),
        ("GlobalSoft Support", 2, "Qualification", 10_000_000_000, 60, 25, 0, 5),
        ("Brightwave Onboarding", 3, "Discovery", 50_000_000_000, 45, 3, 1, 6),
        ("Brightwave Enterprise", 3, "Proposal", 150_000_000_000, 10, 30, 1, 7),
        ("NimbusHQ Starter", 4, "Qualification", 5_000_000_000, 90, 2, 0, 8),
        ("NimbusHQ Growth", 4, "Negotiation", 75_000_000_000, -2, 10, 0, 9),
        # Missing fields deals
        ("Acme Unknown", 0, "Proposal", None, None, 15, 0, None),
        ("Northwind TBD", 1, "Negotiation", 60_000_000_000, None, 20, 1, None),
        # Stale deals
        ("GlobalSoft Legacy", 2, "Qualification", 30_000_000_000, 120, 45, 1, None),
        ("Brightwave Pilot", 3, "Discovery", 8_000_000_000, 60, 35, 0, None),
        # Recent clean deals
        ("NimbusHQ Quick Win", 4, "Proposal", 25_000_000_000, 20, 1, 1, 8),
    ]

    for name, comp_idx, stage, amount_micros, close_days, updated_days, ae_idx, poc_idx in opp_configs:
        comp_id = ids["companies"][comp_idx]
        close_date = (
            f'"{(now + timedelta(days=close_days)).strftime("%Y-%m-%dT00:00:00Z")}"'
            if close_days is not None else "null"
        )
        updated_at = (now - timedelta(days=updated_days)).strftime("%Y-%m-%dT00:00:00Z")
        amount_field = (
            f'amount: {{ amountMicros: {amount_micros}, currencyCode: "USD" }}'
            if amount_micros is not None else ""
        )
        poc_field = (
            f'pointOfContactId: "{ids["people"][poc_idx]}"'
            if poc_idx is not None else ""
        )

        mutation = f'''
            mutation {{ createOpportunity(data: {{
                name: "{name}"
                stage: "{stage}"
                companyId: "{comp_id}"
                {amount_field}
                closeDate: {close_date}
                {poc_field}
            }}) {{ id }} }}
        '''
        result = _gql_mutation(client, mutation)
        oid = result["createOpportunity"]["id"]
        ids["opportunities"].append(oid)

    # Create tasks (activities) with varying recency
    task_configs = [
        # (opp_index, days_ago, title)
        (0, 18, "Follow-up call"),
        (1, 2, "Sent proposal"),
        (2, 25, "Discovery meeting"),
        (3, 4, "Demo scheduled"),
        (4, 1, "Contract review"),
        (6, 3, "Kickoff call"),
        (8, 1, "Intro meeting"),
        (14, 1, "Pricing discussion"),
    ]

    for opp_idx, days_ago, title in task_configs:
        opp_id = ids["opportunities"][opp_idx]
        created = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT10:00:00Z")
        result = _gql_mutation(client, f'''
            mutation {{ createTask(data: {{
                title: "{title}"
                status: "DONE"
            }}) {{ id }} }}
        ''')
        task_id = result["createTask"]["id"]
        ids["tasks"].append(task_id)

        # Link task to opportunity via taskTarget
        _gql_mutation(client, f'''
            mutation {{ createTaskTarget(data: {{
                taskId: "{task_id}"
                opportunityId: "{opp_id}"
            }}) {{ id }} }}
        ''')

    # Summary
    print(f"\nSeeded: {len(ids['companies'])} companies, {len(ids['people'])} people, "
          f"{len(ids['opportunities'])} opportunities, {len(ids['tasks'])} tasks")

    # Save IDs
    output_path = Path(__file__).parent / "seed_output.json"
    with open(output_path, "w") as f:
        json.dump(ids, f, indent=2)
    print(f"IDs saved to {output_path}")

    client.close()


if __name__ == "__main__":
    seed()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/seed_twenty.py
git commit -m "feat: seed script — populate Twenty CRM with sample pipeline data"
```

---

## Task 18: Smoke Test

**Files:**
- Create: `pipeline_coach/smoke_test.py`

- [ ] **Step 1: Implement smoke test**

```python
# pipeline_coach/smoke_test.py
"""Compose smoke test: verify connectivity, schema, config, and dry-run the pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def smoke_test(config_dir: Path = Path("config")) -> None:
    errors: list[str] = []

    # 1. Check config loads
    print("[1/4] Loading configuration...")
    try:
        from pipeline_coach.config import (
            load_app_config,
            load_escalation_config,
            load_rules_config,
        )

        app_config = load_app_config()
        rules_config = load_rules_config(config_dir / "rules.yaml")
        escalation_config = load_escalation_config(config_dir / "escalation.yaml")
        print("  OK: Config loaded")
    except Exception as e:
        errors.append(f"Config load failed: {e}")
        print(f"  FAIL: {e}")
        _report(errors)
        return

    # 2. Check Twenty connectivity
    print("[2/4] Connecting to Twenty CRM...")
    try:
        from pipeline_coach.ingestion.twenty_client import TwentyClient

        client = TwentyClient(
            base_url=app_config.twenty_api_url,
            api_key=app_config.twenty_api_key,
        )
        companies = client.fetch_all("companies", "{ id name }")
        print(f"  OK: Connected, found {len(companies)} companies")
    except Exception as e:
        errors.append(f"Twenty connection failed: {e}")
        print(f"  FAIL: {e}")
        _report(errors)
        return

    # 3. Check schema fields exist
    print("[3/4] Verifying schema fields...")
    try:
        opps = client.fetch_all(
            "opportunities",
            "{ id name amount { amountMicros currencyCode } stage closeDate "
            "createdAt updatedAt companyId pointOfContactId ownerId }",
        )
        print(f"  OK: Opportunity fields valid, found {len(opps)} opportunities")

        members = client.fetch_all(
            "workspaceMembers", "{ id name { firstName lastName } userEmail }"
        )
        print(f"  OK: WorkspaceMember fields valid, found {len(members)} members")
    except Exception as e:
        errors.append(f"Schema validation failed: {e}")
        print(f"  FAIL: {e}")

    # 4. Dry-run pipeline (no email sending)
    print("[4/4] Dry-running pipeline (no emails)...")
    try:
        from unittest.mock import MagicMock

        from pipeline_coach.workflow.graph import build_graph
        from datetime import date

        mock_email = MagicMock()
        mock_email.send.return_value = "dry-run"

        graph = build_graph(
            twenty_client=client,
            email_client=mock_email,
            rules_config=rules_config,
            escalation_config=escalation_config,
            use_llm=False,
            today=date.today(),
        )
        result = graph.invoke({
            "companies": [], "people": [], "opportunities": [],
            "tasks": [], "workspace_members": [],
            "contexts": [], "issue_summaries": [],
            "ae_briefs": {}, "escalation_briefs": {},
            "action_retry_count_by_opp": {},
            "run_id": "smoke-test",
            "emails_sent": 0, "emails_failed": 0,
            "errors": [],
        })
        n_issues = len(result["issue_summaries"])
        n_briefs = len(result["ae_briefs"])
        print(f"  OK: Pipeline ran — {n_issues} issues, {n_briefs} AE briefs generated")
        if result["errors"]:
            for err in result["errors"]:
                print(f"  WARN: {err}")
    except Exception as e:
        errors.append(f"Pipeline dry-run failed: {e}")
        print(f"  FAIL: {e}")

    client.close()
    _report(errors)


def _report(errors: list[str]) -> None:
    print()
    if errors:
        print(f"SMOKE TEST FAILED ({len(errors)} error(s)):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("SMOKE TEST PASSED")
        sys.exit(0)


if __name__ == "__main__":
    smoke_test()
```

- [ ] **Step 2: Commit**

```bash
git add pipeline_coach/smoke_test.py
git commit -m "feat: smoke test — verify connectivity, schema, and dry-run pipeline"
```

---

## Task 19: Docker + DSPy Configuration

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

CMD ["python", "-m", "pipeline_coach"]
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
services:
  twenty-db:
    image: postgres:15
    volumes:
      - twenty_pg_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: twenty
      POSTGRES_USER: twenty
      POSTGRES_PASSWORD: twenty

  twenty:
    image: twentyhq/twenty:latest
    depends_on:
      - twenty-db
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgres://twenty:twenty@twenty-db:5432/twenty
      SERVER_URL: http://localhost:3000
      FRONT_BASE_URL: http://localhost:3000

  pipeline-coach:
    build: .
    depends_on:
      - twenty
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./data:/app/data

  pipeline-coach-smoke:
    build: .
    depends_on:
      - twenty
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./data:/app/data
    command: ["python", "-m", "pipeline_coach.smoke_test"]

volumes:
  twenty_pg_data:
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: Dockerfile and docker-compose with Twenty + Pipeline Coach services"
```

---

## Task 20: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

```markdown
# Pipeline Coach

A daily pipeline hygiene coach that connects to a self-hosted [Twenty CRM](https://twenty.com), scans deals for issues, and emails each AE a prioritized action list. Critical deals are escalated to managers.

**License:** Apache 2.0

## Quickstart

```bash
# 1. Configure secrets
cp .env.example .env
# Edit .env with your Twenty API key, Resend API key, etc.

# 2. Start services
docker compose up -d

# 3. Seed sample data (optional)
python scripts/seed_twenty.py

# 4. Run once manually
python -m pipeline_coach --once
```

## How It Works

Pipeline Coach runs a daily pipeline via [LangGraph](https://github.com/langchain-ai/langgraph):

1. **Parallel data fetch** — pulls companies, people, opportunities, tasks, and workspace members from Twenty's GraphQL API concurrently
2. **Issue detection** — applies configurable hygiene rules (stale deals, missing fields, unrealistic dates)
3. **Action suggestions** — uses [DSPy](https://dspy.ai) to generate concise next-best-actions per deal (with deterministic fallback)
4. **Quality gate** — validates LLM suggestions; retries up to 2x, then falls back to templates
5. **Routing** — groups issues by AE; critical deals (high priority + large amount) escalate to managers
6. **Email delivery** — sends daily briefs via [Resend](https://resend.com)

## Configuration

### Rules (`config/rules.yaml`)

Tune hygiene thresholds per stage:

```yaml
rules:
  stale_in_stage:
    default_days: 14
    by_stage:
      Negotiation: 7
  no_recent_activity:
    days: 7
```

### Escalation (`config/escalation.yaml`)

Map AEs to managers:

```yaml
escalation:
  default_manager: vp-sales@demo.com
  overrides:
    alex@demo.com: manager-a@demo.com
  critical_amount_threshold: 50000
```

### Environment (`.env`)

See `.env.example` for all variables. Secrets stay in `.env` (gitignored). For production, use a dedicated secrets manager.

## Running

| Command | Description |
|---|---|
| `python -m pipeline_coach --once` | Run pipeline once and exit |
| `python -m pipeline_coach` | Start scheduler (runs daily at `RUN_AT_HOUR`) |
| `python -m pipeline_coach.show_recent --owner alex@demo.com` | View most recent brief for an owner |
| `docker compose run --rm pipeline-coach-smoke` | Run integration smoke test |

## Testing

v1 includes **unit tests** for core business logic (rules, priority, brief rendering, quality gate, normalizer) with mocked external services:

```bash
pip install -e ".[dev]"
pytest
```

A **compose smoke test** verifies end-to-end connectivity, schema fields, and a dry-run pipeline (no emails sent):

```bash
docker compose run --rm pipeline-coach-smoke
```

**Future (v2+):** full integration test suites against real Twenty/Resend and contract tests for GraphQL + email payloads.

## Architecture

**Monolith package** (`pipeline_coach/`) for v1. Future versions may decompose into separate services if scale demands it.

- **Read-only** with respect to Twenty CRM — never modifies records
- **Agent identity** — uses dedicated API credentials for audit trail
- **Slack** — intentionally not implemented in v1; message rendering is designed to be reusable for Slack DMs

## Tech Stack

Python 3.12 | LangGraph | DSPy | httpx | Pydantic | Resend | PyYAML | APScheduler | structlog
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart, configuration, architecture, and testing notes"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Twenty CRM integration (GraphQL, read-only) — Tasks 4, 5
- [x] Hygiene rules (configurable, per-stage) — Task 6
- [x] Priority scoring — Task 7
- [x] DSPy suggested actions + fallback — Task 8
- [x] Quality gate with retry loop — Task 9
- [x] AE briefs + manager escalation emails — Tasks 10, 12
- [x] Resend email delivery — Task 11
- [x] LangGraph workflow (parallel fetch, retry loop, conditional routing) — Task 13
- [x] Scheduling (APScheduler) + run_once + __main__ — Task 15
- [x] Observability (structured logging, audit JSONL) — Task 14
- [x] show_recent CLI — Task 16
- [x] Seed script — Task 17
- [x] Smoke test — Task 18
- [x] Docker Compose — Task 19
- [x] README — Task 20
- [x] Issue model with rule_id (spec addition) — Task 2
- [x] Per-opp retry tracking — Task 13
- [x] Privacy controls (AUDIT_REDACT_PII) — Task 14
- [x] Apache 2.0 license — Task 1

**Placeholder scan:** No TBD/TODO/placeholder text found.

**Type consistency:** `OpportunityContext`, `Issue`, `IssueSummary` used consistently across all tasks. `evaluate_opportunity` returns `list[Issue]`. `compute_priority` returns `Literal["high", "medium", "low"]`. `PipelineState` TypedDict matches graph node I/O signatures. `validate_action` signature consistent between Task 9 definition and Task 13 usage.

---

## Eng Review Amendments (2026-03-30)

The following changes were agreed during `/plan-eng-review` and must be applied during implementation:

### Architecture changes
1. **SEVERITY_RANK consolidation** — move `SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}` to `models.py` as a module constant. Remove duplicates from `priority.py` and `actions.py`.
2. **Split retry state** — replace single `issue_summaries` in `PipelineState` with `validated_summaries: list[IssueSummary]` and `pending_summaries: list[IssueSummary]`. `generate_actions` processes only pending, `validate_actions` moves items between lists.
3. **Brief dataclass** — `render_ae_brief()` and `render_escalation_brief()` return a `Brief(subject: str, body: str)` dataclass instead of raw text. `PipelineState` uses `Dict[str, Brief]` for `ae_briefs` and `escalation_briefs`. `send_emails` reads `.subject` and `.body` directly.
4. **`stageChangedAt` custom field** — add to Twenty via seed script. Normalizer reads it for `days_in_stage` instead of `updatedAt`. Document in spec's Validated Against section.
5. **Filter closed stages** — add `excluded_stages` to `rules.yaml` (default: `["Closed Won", "Closed Lost"]`). Normalizer skips opportunities in excluded stages. Configurable by RevOps.
6. **Docker Compose health check** — add `healthcheck` to the `twenty` service. Use `depends_on: condition: service_healthy` for `pipeline-coach` and `pipeline-coach-smoke`.
7. **Update spec** — add `workspaceMembers` and `stageChangedAt` to the "Validated Against" section.

### Testing additions
8. **Audit record tests** — add `tests/test_audit.py` with tests for JSONL output format, PII redaction, and record structure.
9. **Node-level workflow tests** — extract node functions from `build_graph` closures to module-level functions. Add 6-8 unit tests for: fetch error handling, `join_data` merging, `should_retry_actions` routing, retry loop state transitions.
10. **Additional edge case tests** — add to existing test files: malformed YAML config, missing workspace member in normalizer, HTTP timeout in TwentyClient, DSPy exception fallback in actions.

### Minor fixes
11. **Pagination circuit breaker** — add `max_pages=50` parameter to `TwentyClient.fetch_all()`. Raise after limit.
12. **Rate limit sleep** — add `time.sleep(0.6)` between pagination pages as a rate limit safety valve.
13. **Seed script idempotency** — add `--clean` flag and check for existing seed data before creating duplicates.
14. **Audit log error handling** — wrap `write_audit_record` file write in try/except with log warning on failure.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 9 issues, 1 critical gap, all resolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

- **OUTSIDE VOICE:** Claude subagent found 12 issues. 3 cross-model tensions resolved (days_in_stage semantic bug, closed deals filter, Docker health check). LangGraph/DSPy choices confirmed as deliberate.
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready to implement
