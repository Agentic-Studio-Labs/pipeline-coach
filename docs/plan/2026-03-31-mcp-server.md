# Pipeline Coach MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP server that exposes Pipeline Coach's pipeline intelligence (hygiene analysis, deal overviews, audit history) as tools and resources accessible from Claude Code, Cursor, and other MCP clients via stdio transport.

**Architecture:** In-repo subpackage `pipeline_coach/mcp/` using the official `mcp` Python SDK (FastMCP API). Tools call into existing Pipeline Coach modules (normalizer, rules, priority, actions) for live CRM data analysis. Audit tools read from local JSONL. All tools are read-only.

**Tech Stack:** mcp Python SDK (FastMCP), existing pipeline_coach modules, stdio transport

**Design spec:** `docs/design/2026-03-31-mcp-server-design.md`

---

## File Structure

```
pipeline_coach/mcp/
├── __init__.py            # Package marker
├── __main__.py            # Entry point: python -m pipeline_coach.mcp
├── server.py              # FastMCP instance, tool/resource registration, startup
├── helpers.py             # Shared: fetch + normalize from Twenty, fuzzy match, CRM links, audit reader
└── tools.py               # All 8 tool handler functions
tests/
└── test_mcp_tools.py      # Unit tests for tool handlers with mocked Twenty
```

Changes to existing files:
- `pyproject.toml` — add `mcp` optional extra

---

## Task 1: Scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `pipeline_coach/mcp/__init__.py`
- Create: `pipeline_coach/mcp/__main__.py`

- [ ] **Step 1: Add mcp optional dependency to pyproject.toml**

Add to the existing `[project.optional-dependencies]` table (do not remove `dev`):

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.6.0",
]
```

- [ ] **Step 2: Create package __init__.py**

```python
# pipeline_coach/mcp/__init__.py
```

Empty file.

- [ ] **Step 3: Create __main__.py entry point**

```python
# pipeline_coach/mcp/__main__.py
from __future__ import annotations

from dotenv import load_dotenv


def main() -> None:
    load_dotenv(override=True)
    from pipeline_coach.mcp.server import mcp

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Install the mcp extra**

```bash
pip install -e ".[dev,mcp]"
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml pipeline_coach/mcp/
git commit -m "feat(mcp): scaffolding — add mcp optional dependency and entry point"
```

---

## Task 2: Helpers Module

**Files:**
- Create: `pipeline_coach/mcp/helpers.py`
- Create: `tests/test_mcp_helpers.py`

This module provides shared functions used by all tools: fetching and normalizing CRM data, fuzzy matching, CRM link construction, and audit log reading.

- [ ] **Step 1: Write tests for helpers**

```python
# tests/test_mcp_helpers.py
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline_coach.mcp.helpers import (
    build_crm_link,
    fetch_all_contexts,
    fuzzy_match_company,
    fuzzy_match_opportunity,
    read_audit_runs,
    read_run_issues,
)
from pipeline_coach.models import OpportunityContext


@pytest.fixture()
def sample_contexts() -> list[OpportunityContext]:
    return [
        OpportunityContext(
            id="opp-1", name="Acme Expansion", stage="PROPOSAL",
            owner_email="alex@demo.com", company_name="Acme Corp",
            amount=120_000.0, close_date=date(2026, 4, 15),
        ),
        OpportunityContext(
            id="opp-2", name="Acme Renewal", stage="MEETING",
            owner_email="alex@demo.com", company_name="Acme Corp",
            amount=30_000.0,
        ),
        OpportunityContext(
            id="opp-3", name="Northwind Migration", stage="PROPOSAL",
            owner_email="jordan@demo.com", company_name="Northwind",
            amount=80_000.0,
        ),
    ]


class TestFuzzyMatchOpportunity:
    def test_exact_id_match(self, sample_contexts: list[OpportunityContext]) -> None:
        match, info = fuzzy_match_opportunity("opp-1", sample_contexts)
        assert match is not None
        assert match.id == "opp-1"
        assert info["match_type"] == "exact_id"

    def test_exact_name_match(self, sample_contexts: list[OpportunityContext]) -> None:
        match, info = fuzzy_match_opportunity("Acme Expansion", sample_contexts)
        assert match is not None
        assert match.name == "Acme Expansion"
        assert info["match_type"] == "exact_name"

    def test_case_insensitive_name(self, sample_contexts: list[OpportunityContext]) -> None:
        match, info = fuzzy_match_opportunity("acme expansion", sample_contexts)
        assert match is not None
        assert match.name == "Acme Expansion"

    def test_substring_match(self, sample_contexts: list[OpportunityContext]) -> None:
        match, info = fuzzy_match_opportunity("Expansion", sample_contexts)
        assert match is not None
        assert match.name == "Acme Expansion"
        assert info["match_type"] == "substring"

    def test_substring_multiple_matches(self, sample_contexts: list[OpportunityContext]) -> None:
        match, info = fuzzy_match_opportunity("Acme", sample_contexts)
        assert match is not None
        assert len(info["other_matches"]) > 0

    def test_no_match(self, sample_contexts: list[OpportunityContext]) -> None:
        match, info = fuzzy_match_opportunity("Nonexistent", sample_contexts)
        assert match is None
        assert info["match_type"] == "none"


class TestFuzzyMatchCompany:
    def test_exact_match(self, sample_contexts: list[OpportunityContext]) -> None:
        matches, info = fuzzy_match_company("Acme Corp", sample_contexts)
        assert len(matches) == 2
        assert info["match_type"] == "exact_name"

    def test_substring_match(self, sample_contexts: list[OpportunityContext]) -> None:
        matches, info = fuzzy_match_company("Acme", sample_contexts)
        assert len(matches) == 2

    def test_no_match(self, sample_contexts: list[OpportunityContext]) -> None:
        matches, info = fuzzy_match_company("Unknown", sample_contexts)
        assert len(matches) == 0
        assert info["match_type"] == "none"


class TestBuildCrmLink:
    def test_with_public_url(self) -> None:
        link = build_crm_link("opp-123", crm_url="https://crm.example.com")
        assert link == "https://crm.example.com/object/opportunity/opp-123"

    def test_strips_trailing_slash(self) -> None:
        link = build_crm_link("opp-123", crm_url="http://localhost:3000/")
        assert link == "http://localhost:3000/object/opportunity/opp-123"


class TestReadAuditRuns:
    def test_reads_run_records(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        audit_file.write_text(
            json.dumps({"type": "run", "run_id": "r1", "timestamp": "2026-03-30T10:00:00Z",
                         "opportunities_with_issues": 3, "emails_sent": 1, "emails_failed": 0,
                         "errors": []}) + "\n"
            + json.dumps({"type": "issue", "run_id": "r1", "opportunity_name": "Deal A"}) + "\n"
        )
        runs = read_audit_runs(audit_dir=tmp_path, limit=10)
        assert len(runs) == 1
        assert runs[0]["run_id"] == "r1"

    def test_respects_limit(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        lines = []
        for i in range(5):
            lines.append(json.dumps({"type": "run", "run_id": f"r{i}", "timestamp": f"2026-03-3{i}T10:00:00Z",
                                      "opportunities_with_issues": 0, "emails_sent": 0, "emails_failed": 0,
                                      "errors": []}))
        audit_file.write_text("\n".join(lines) + "\n")
        runs = read_audit_runs(audit_dir=tmp_path, limit=3)
        assert len(runs) == 3

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        runs = read_audit_runs(audit_dir=tmp_path, limit=10)
        assert runs == []


class TestReadRunIssues:
    def test_reads_issues_for_run(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        audit_file.write_text(
            json.dumps({"type": "run", "run_id": "r1", "timestamp": "2026-03-30T10:00:00Z",
                         "opportunities_with_issues": 1, "emails_sent": 1, "emails_failed": 0,
                         "errors": ["fetch failed"]}) + "\n"
            + json.dumps({"type": "issue", "run_id": "r1", "opportunity_name": "Deal A",
                          "priority": "high", "rule_ids": ["close_date_past"],
                          "suggested_action": "Update close date", "action_rationale": "Past dates hurt forecast"}) + "\n"
            + json.dumps({"type": "issue", "run_id": "r2", "opportunity_name": "Deal B"}) + "\n"
        )
        run, issues = read_run_issues(run_id="r1", audit_dir=tmp_path)
        assert run is not None
        assert run["errors"] == ["fetch failed"]
        assert len(issues) == 1
        assert issues[0]["opportunity_name"] == "Deal A"

    def test_unknown_run_returns_none(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        audit_file.write_text(
            json.dumps({"type": "run", "run_id": "r1", "timestamp": "2026-03-30T10:00:00Z",
                         "opportunities_with_issues": 0, "emails_sent": 0, "emails_failed": 0,
                         "errors": []}) + "\n"
        )
        run, issues = read_run_issues(run_id="unknown", audit_dir=tmp_path)
        assert run is None
        assert issues == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_helpers.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement helpers.py**

```python
# pipeline_coach/mcp/helpers.py
from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from pipeline_coach.config import (
    AppConfig,
    EscalationConfig,
    RulesConfig,
    load_app_config,
    load_escalation_config,
    load_rules_config,
)
from pipeline_coach.hygiene.priority import compute_priority
from pipeline_coach.hygiene.rules import evaluate_opportunity
from pipeline_coach.ingestion.normalizer import normalize_opportunities
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.models import IssueSummary, OpportunityContext


def get_crm_url(app_config: AppConfig) -> str:
    return app_config.crm_public_url or app_config.twenty_api_url


def build_crm_link(opp_id: str, *, crm_url: str) -> str:
    return f"{crm_url.rstrip('/')}/object/opportunity/{opp_id}"


def fetch_all_contexts(
    twenty_client: TwentyClient,
    rules_config: RulesConfig,
    today: date | None = None,
) -> list[OpportunityContext]:
    today = today or date.today()
    companies = twenty_client.fetch_all("companies", "id name")
    people = twenty_client.fetch_all(
        "people",
        "id name { firstName lastName } emails { primaryEmail } companyId jobTitle",
    )
    opportunities = twenty_client.fetch_all(
        "opportunities",
        "id name amount { amountMicros currencyCode } stage closeDate "
        "createdAt updatedAt stageChangedAt companyId pointOfContactId ownerId",
    )
    tasks = twenty_client.fetch_all(
        "tasks",
        "id createdAt status taskTargets { edges { node { targetOpportunityId } } }",
    )
    workspace_members = twenty_client.fetch_all(
        "workspaceMembers",
        "id name { firstName lastName } userEmail",
    )
    return normalize_opportunities(
        opportunities=opportunities,
        companies=companies,
        people=people,
        workspace_members=workspace_members,
        tasks=tasks,
        today=today,
        excluded_stages=rules_config.excluded_stages,
    )


def evaluate_contexts(
    contexts: list[OpportunityContext],
    rules_config: RulesConfig,
    today: date | None = None,
) -> list[IssueSummary]:
    today = today or date.today()
    summaries: list[IssueSummary] = []
    for ctx in contexts:
        issues = evaluate_opportunity(ctx, rules_config, today=today)
        if not issues:
            continue
        priority = compute_priority(issues, amount=ctx.amount, stage=ctx.stage)
        summaries.append(
            IssueSummary(
                opportunity_id=ctx.id,
                opportunity_name=ctx.name,
                owner_email=ctx.owner_email,
                priority=priority,
                issues=issues,
                context=ctx,
            )
        )
    return summaries


MatchInfo = dict[str, Any]

_UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def fuzzy_match_opportunity(
    query: str, contexts: list[OpportunityContext]
) -> tuple[OpportunityContext | None, MatchInfo]:
    import re

    # 1. Exact ID match
    if re.match(_UUID_RE, query, re.IGNORECASE):
        for ctx in contexts:
            if ctx.id == query:
                return ctx, {"matched_name": ctx.name, "match_type": "exact_id", "other_matches": []}

    # 2. Case-insensitive exact name match
    query_lower = query.lower()
    for ctx in contexts:
        if ctx.name.lower() == query_lower:
            return ctx, {"matched_name": ctx.name, "match_type": "exact_name", "other_matches": []}

    # 3. Case-insensitive substring match
    matches = [ctx for ctx in contexts if query_lower in ctx.name.lower()]
    if matches:
        other = [m.name for m in matches[1:6]]
        return matches[0], {"matched_name": matches[0].name, "match_type": "substring", "other_matches": other}

    return None, {"matched_name": None, "match_type": "none", "other_matches": []}


def fuzzy_match_company(
    company_name: str, contexts: list[OpportunityContext]
) -> tuple[list[OpportunityContext], MatchInfo]:
    query_lower = company_name.lower()

    # Exact company name match
    exact = [ctx for ctx in contexts if (ctx.company_name or "").lower() == query_lower]
    if exact:
        resolved = exact[0].company_name or company_name
        return exact, {"matched_name": resolved, "match_type": "exact_name", "other_matches": []}

    # Substring match
    partial = [ctx for ctx in contexts if query_lower in (ctx.company_name or "").lower()]
    if partial:
        resolved = partial[0].company_name or company_name
        company_names = list({ctx.company_name for ctx in partial if ctx.company_name})
        other = [n for n in company_names[1:6] if n != resolved]
        return partial, {"matched_name": resolved, "match_type": "substring", "other_matches": other}

    return [], {"matched_name": None, "match_type": "none", "other_matches": []}


def read_audit_runs(*, audit_dir: Path | None = None, limit: int = 10) -> list[dict]:
    audit_dir = audit_dir or Path("data")
    audit_file = audit_dir / "audit_log.jsonl"
    if not audit_file.exists():
        return []

    runs: list[dict] = []
    with open(audit_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("type") == "run":
                    runs.append(record)
            except json.JSONDecodeError:
                continue

    return runs[-limit:]


def read_run_issues(
    *, run_id: str, audit_dir: Path | None = None
) -> tuple[dict | None, list[dict]]:
    audit_dir = audit_dir or Path("data")
    audit_file = audit_dir / "audit_log.jsonl"
    if not audit_file.exists():
        return None, []

    run_record: dict | None = None
    issues: list[dict] = []
    with open(audit_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("run_id") != run_id:
                continue
            if record.get("type") == "run":
                run_record = record
            elif record.get("type") == "issue":
                issues.append(record)

    return run_record, issues


def generate_mcp_run_id() -> str:
    return f"mcp-{uuid.uuid4().hex[:8]}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_mcp_helpers.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/mcp/helpers.py tests/test_mcp_helpers.py
git commit -m "feat(mcp): helpers — fetch, fuzzy match, CRM links, audit reader"
```

---

## Task 3: Tool Handlers

**Files:**
- Create: `pipeline_coach/mcp/tools.py`
- Create: `tests/test_mcp_tools.py`

All 8 tool handler functions. Each returns a dict that FastMCP will serialize as structured JSON.

- [ ] **Step 1: Write tests for tool handlers**

```python
# tests/test_mcp_tools.py
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline_coach.config import RulesConfig, load_rules_config
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
from pipeline_coach.models import OpportunityContext


@pytest.fixture()
def rules_config(tmp_path: Path) -> RulesConfig:
    content = """\
excluded_stages:
  - CUSTOMER

rules:
  stale_in_stage:
    enabled: true
    default_days: 14
    by_stage:
      PROPOSAL: 7
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
      PROPOSAL: true
    severity: low
"""
    p = tmp_path / "rules.yaml"
    p.write_text(content)
    return load_rules_config(p)


@pytest.fixture()
def sample_contexts() -> list[OpportunityContext]:
    return [
        OpportunityContext(
            id="opp-1", name="Acme Expansion", stage="PROPOSAL",
            owner_email="alex@demo.com", owner_name="Alex Doe",
            company_name="Acme Corp", amount=120_000.0,
            close_date=date(2026, 3, 15), days_in_stage=21,
            days_since_last_activity=18, has_decision_maker=True,
        ),
        OpportunityContext(
            id="opp-2", name="Brightwave Onboarding", stage="MEETING",
            owner_email="jordan@demo.com", owner_name="Jordan Lee",
            company_name="Brightwave", amount=50_000.0,
            close_date=date(2026, 5, 1), days_in_stage=3,
            days_since_last_activity=2, has_decision_maker=True,
        ),
    ]


class TestHandleAnalyzePipeline:
    def test_returns_structured_results(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_analyze_pipeline(
                use_llm=False,
                twenty_client=MagicMock(),
                rules_config=rules_config,
                crm_url="http://localhost:3000",
                today=date(2026, 3, 30),
            )
        assert result["run_id"].startswith("mcp-")
        assert result["total_opportunities"] == 2
        assert result["issues_found"] >= 1
        assert len(result["summaries"]) >= 1
        assert "crm_link" in result["summaries"][0]

    def test_clean_deals_return_zero_issues(
        self, rules_config: RulesConfig
    ) -> None:
        clean = [OpportunityContext(
            id="opp-clean", name="Clean Deal", stage="MEETING",
            owner_email="a@b.com", amount=10_000.0,
            close_date=date(2026, 5, 1), days_in_stage=2,
            days_since_last_activity=1, has_decision_maker=True,
        )]
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=clean):
            result = handle_analyze_pipeline(
                use_llm=False,
                twenty_client=MagicMock(),
                rules_config=rules_config,
                crm_url="http://localhost:3000",
                today=date(2026, 3, 30),
            )
        assert result["issues_found"] == 0
        assert result["summaries"] == []


class TestHandleGetDealOverview:
    def test_finds_deal_by_name(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_get_deal_overview(
                query="Acme Expansion", use_llm=False,
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="http://localhost:3000", today=date(2026, 3, 30),
            )
        assert result["opportunity"]["name"] == "Acme Expansion"
        assert result["match_info"]["match_type"] == "exact_name"
        assert result["crm_link"].endswith("/opp-1")

    def test_not_found(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_get_deal_overview(
                query="Nonexistent", use_llm=False,
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="http://localhost:3000", today=date(2026, 3, 30),
            )
        assert result["error"] == "No matching opportunity found"


class TestHandleGetCompanyOverview:
    def test_returns_company_deals(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_get_company_overview(
                company_name="Acme Corp",
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="http://localhost:3000", today=date(2026, 3, 30),
            )
        assert result["company_name"] == "Acme Corp"
        assert result["total_opportunities"] == 1
        assert len(result["opportunities"]) == 1


class TestHandleGetDealIssues:
    def test_returns_issues(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_get_deal_issues(
                query="Acme Expansion",
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="http://localhost:3000", today=date(2026, 3, 30),
            )
        assert result["opportunity_name"] == "Acme Expansion"
        assert len(result["issues"]) >= 1


class TestHandleListStaleDeals:
    def test_returns_stale_deals(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_list_stale_deals(
                min_days=None,
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="http://localhost:3000", today=date(2026, 3, 30),
            )
        assert result["count"] >= 1
        assert "days_in_stage" in result["deals"][0]

    def test_min_days_filter(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_list_stale_deals(
                min_days=100,
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="http://localhost:3000", today=date(2026, 3, 30),
            )
        assert result["count"] == 0


class TestHandleAuditHistory:
    def test_returns_runs(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        audit_file.write_text(
            json.dumps({"type": "run", "run_id": "r1", "timestamp": "2026-03-30T10:00:00Z",
                         "opportunities_with_issues": 3, "emails_sent": 1, "emails_failed": 0,
                         "errors": []}) + "\n"
        )
        result = handle_get_audit_history(limit=10, audit_dir=tmp_path)
        assert len(result["runs"]) == 1
        assert result["runs"][0]["run_id"] == "r1"


class TestHandleGetRunDetails:
    def test_returns_run_and_issues(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        audit_file.write_text(
            json.dumps({"type": "run", "run_id": "r1", "timestamp": "2026-03-30T10:00:00Z",
                         "opportunities_with_issues": 1, "emails_sent": 1, "emails_failed": 0,
                         "errors": []}) + "\n"
            + json.dumps({"type": "issue", "run_id": "r1", "opportunity_name": "Deal A",
                          "priority": "high", "rule_ids": ["close_date_past"]}) + "\n"
        )
        result = handle_get_run_details(run_id="r1", audit_dir=tmp_path)
        assert result["run"]["run_id"] == "r1"
        assert len(result["issues"]) == 1

    def test_unknown_run(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit_log.jsonl"
        audit_file.write_text(
            json.dumps({"type": "run", "run_id": "r1", "timestamp": "2026-03-30T10:00:00Z",
                         "opportunities_with_issues": 0, "emails_sent": 0, "emails_failed": 0,
                         "errors": []}) + "\n"
        )
        result = handle_get_run_details(run_id="unknown", audit_dir=tmp_path)
        assert result["error"] == "Run not found"


class TestHandleGetRulesConfig:
    def test_returns_config(self, tmp_path: Path) -> None:
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("excluded_stages:\n  - CUSTOMER\nrules:\n  stale_in_stage:\n    enabled: true\n    default_days: 14\n    severity: medium\n")
        result = handle_get_rules_config(config_dir=tmp_path)
        assert "CUSTOMER" in result["excluded_stages"]
        assert "stale_in_stage" in result["rules"]


class TestCrmLinkUsesPublicUrl:
    def test_public_url_preferred(
        self, rules_config: RulesConfig, sample_contexts: list[OpportunityContext]
    ) -> None:
        with patch("pipeline_coach.mcp.tools.fetch_all_contexts", return_value=sample_contexts):
            result = handle_get_deal_overview(
                query="Acme Expansion", use_llm=False,
                twenty_client=MagicMock(), rules_config=rules_config,
                crm_url="https://crm.public.com", today=date(2026, 3, 30),
            )
        assert result["crm_link"].startswith("https://crm.public.com/")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_tools.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement tools.py**

```python
# pipeline_coach/mcp/tools.py
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from pipeline_coach.coach.actions import generate_suggested_action_with_rationale
from pipeline_coach.config import RulesConfig
from pipeline_coach.hygiene.priority import compute_priority
from pipeline_coach.hygiene.rules import evaluate_opportunity
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.mcp.helpers import (
    build_crm_link,
    evaluate_contexts,
    fetch_all_contexts,
    fuzzy_match_company,
    fuzzy_match_opportunity,
    generate_mcp_run_id,
    read_audit_runs,
    read_run_issues,
)
from pipeline_coach.models import OpportunityContext


def handle_analyze_pipeline(
    *,
    use_llm: bool,
    twenty_client: TwentyClient,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    contexts = fetch_all_contexts(twenty_client, rules_config, today)
    summaries = evaluate_contexts(contexts, rules_config, today)

    result_summaries = []
    for s in summaries:
        action, rationale = generate_suggested_action_with_rationale(
            ctx=s.context, issues=s.issues, use_llm=use_llm,
        )
        result_summaries.append({
            "opportunity_name": s.opportunity_name,
            "company_name": s.context.company_name,
            "owner_email": s.owner_email,
            "stage": s.context.stage,
            "amount": s.context.amount,
            "priority": s.priority,
            "issues": [{"rule_id": i.rule_id, "severity": i.severity, "message": i.message} for i in s.issues],
            "suggested_action": action,
            "action_rationale": rationale,
            "crm_link": build_crm_link(s.opportunity_id, crm_url=crm_url),
        })

    return {
        "run_id": generate_mcp_run_id(),
        "total_opportunities": len(contexts),
        "issues_found": len(result_summaries),
        "summaries": result_summaries,
    }


def handle_get_deal_overview(
    *,
    query: str,
    use_llm: bool,
    twenty_client: TwentyClient,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    contexts = fetch_all_contexts(twenty_client, rules_config, today)
    match, match_info = fuzzy_match_opportunity(query, contexts)

    if match is None:
        return {"error": "No matching opportunity found", "match_info": match_info}

    issues = evaluate_opportunity(match, rules_config, today=today)
    priority = compute_priority(issues, amount=match.amount, stage=match.stage) if issues else None
    action, rationale = (None, None)
    if issues:
        action, rationale = generate_suggested_action_with_rationale(
            ctx=match, issues=issues, use_llm=use_llm,
        )

    return {
        "opportunity": match.model_dump(mode="json"),
        "issues": [{"rule_id": i.rule_id, "severity": i.severity, "message": i.message, "details": i.details} for i in issues],
        "priority": priority,
        "suggested_action": action,
        "action_rationale": rationale,
        "crm_link": build_crm_link(match.id, crm_url=crm_url),
        "match_info": match_info,
    }


def handle_get_company_overview(
    *,
    company_name: str,
    twenty_client: TwentyClient,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    contexts = fetch_all_contexts(twenty_client, rules_config, today)
    matches, match_info = fuzzy_match_company(company_name, contexts)

    if not matches:
        return {"error": "No matching company found", "match_info": match_info}

    resolved_name = match_info["matched_name"]
    opps = []
    healthy = 0
    flagged = 0
    total_value = 0.0

    for ctx in matches:
        issues = evaluate_opportunity(ctx, rules_config, today=today)
        if ctx.amount:
            total_value += ctx.amount

        opp: dict[str, Any] = {
            "name": ctx.name,
            "stage": ctx.stage,
            "amount": ctx.amount,
            "owner_email": ctx.owner_email,
            "close_date": str(ctx.close_date) if ctx.close_date else None,
            "crm_link": build_crm_link(ctx.id, crm_url=crm_url),
        }

        if issues:
            flagged += 1
            opp["status"] = "flagged"
            opp["issues"] = [{"rule_id": i.rule_id, "severity": i.severity, "message": i.message} for i in issues]
            action, _ = generate_suggested_action_with_rationale(ctx=ctx, issues=issues, use_llm=False)
            opp["suggested_action"] = action
        else:
            healthy += 1
            opp["status"] = "healthy"

        opps.append(opp)

    return {
        "company_name": resolved_name,
        "total_opportunities": len(matches),
        "healthy": healthy,
        "flagged": flagged,
        "total_pipeline_value": total_value,
        "opportunities": opps,
        "match_info": match_info,
    }


def handle_get_deal_issues(
    *,
    query: str,
    twenty_client: TwentyClient,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    contexts = fetch_all_contexts(twenty_client, rules_config, today)
    match, match_info = fuzzy_match_opportunity(query, contexts)

    if match is None:
        return {"error": "No matching opportunity found", "match_info": match_info}

    issues = evaluate_opportunity(match, rules_config, today=today)
    priority = compute_priority(issues, amount=match.amount, stage=match.stage) if issues else None

    return {
        "opportunity_name": match.name,
        "stage": match.stage,
        "amount": match.amount,
        "issues": [{"rule_id": i.rule_id, "severity": i.severity, "message": i.message} for i in issues],
        "priority": priority,
        "match_info": match_info,
    }


def handle_list_stale_deals(
    *,
    min_days: int | None,
    twenty_client: TwentyClient,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    contexts = fetch_all_contexts(twenty_client, rules_config, today)
    cfg = rules_config.stale_in_stage
    if not cfg.enabled:
        return {"count": 0, "deals": []}

    deals = []
    for ctx in contexts:
        if ctx.days_in_stage is None:
            continue
        threshold = cfg.by_stage.get(ctx.stage, cfg.default_days)
        if ctx.days_in_stage <= threshold:
            continue
        if min_days is not None and ctx.days_in_stage < min_days:
            continue
        deals.append({
            "name": ctx.name,
            "company_name": ctx.company_name,
            "stage": ctx.stage,
            "days_in_stage": ctx.days_in_stage,
            "threshold": threshold,
            "owner_email": ctx.owner_email,
            "crm_link": build_crm_link(ctx.id, crm_url=crm_url),
        })

    return {"count": len(deals), "deals": deals}


def handle_get_audit_history(
    *, limit: int = 10, audit_dir: Path | None = None
) -> dict[str, Any]:
    runs = read_audit_runs(audit_dir=audit_dir, limit=limit)
    return {"runs": runs}


def handle_get_run_details(
    *, run_id: str, audit_dir: Path | None = None
) -> dict[str, Any]:
    run, issues = read_run_issues(run_id=run_id, audit_dir=audit_dir)
    if run is None:
        return {"error": "Run not found"}
    return {"run": run, "issues": issues, "errors": run.get("errors", [])}


def handle_get_rules_config(
    *, config_dir: Path | None = None
) -> dict[str, Any]:
    config_dir = config_dir or Path("config")
    rules_path = config_dir / "rules.yaml"
    with open(rules_path) as f:
        data = yaml.safe_load(f)
    return {
        "excluded_stages": data.get("excluded_stages", []),
        "rules": data.get("rules", {}),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_mcp_tools.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline_coach/mcp/tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): tool handlers — 8 tools for pipeline analysis, audit, and config"
```

---

## Task 4: Server (FastMCP wiring + Resources)

**Files:**
- Create: `pipeline_coach/mcp/server.py`

- [ ] **Step 1: Implement server.py**

```python
# pipeline_coach/mcp/server.py
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pipeline_coach.config import load_app_config, load_escalation_config, load_rules_config
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.mcp.helpers import get_crm_url
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

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

# --- Lazy-initialized server state ---
_twenty_client: TwentyClient | None = None
_app_config = None
_rules_config = None
_escalation_config = None
_crm_url: str = ""
_config_dir = Path("config")


def _ensure_initialized() -> None:
    global _twenty_client, _app_config, _rules_config, _escalation_config, _crm_url
    if _twenty_client is not None:
        return
    _app_config = load_app_config()
    _rules_config = load_rules_config(_config_dir / "rules.yaml")
    _escalation_config = load_escalation_config(_config_dir / "escalation.yaml")
    _twenty_client = TwentyClient(
        base_url=_app_config.twenty_api_url, api_key=_app_config.twenty_api_key,
    )
    _crm_url = get_crm_url(_app_config)

    if _app_config.llm_api_key:
        import dspy
        from dspy.adapters import ChatAdapter

        lm = dspy.LM(_app_config.llm_model, api_key=_app_config.llm_api_key, temperature=0.7, max_tokens=200)
        dspy.configure(lm=lm, adapter=ChatAdapter())


# --- FastMCP instance ---

mcp = FastMCP(
    "pipeline-coach",
    instructions="Pipeline Coach: query CRM deal health, run hygiene analysis, and inspect audit history.",
)


# --- Tools ---

@mcp.tool(annotations=_READ_ONLY)
def analyze_pipeline(
    use_llm: Annotated[bool, Field(default=False, description="Use LLM for action suggestions (slower, requires LLM_API_KEY)")] = False,
) -> dict[str, Any]:
    """Run full hygiene analysis on all open CRM opportunities. Returns prioritized issues and suggested actions."""
    _ensure_initialized()
    return handle_analyze_pipeline(
        use_llm=use_llm, twenty_client=_twenty_client, rules_config=_rules_config,
        crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_deal_overview(
    query: Annotated[str, Field(description="Opportunity name or ID")],
    use_llm: Annotated[bool, Field(default=False, description="Use LLM for action suggestion")] = False,
) -> dict[str, Any]:
    """Deep dive on a single opportunity: full context, issues, suggested action, and CRM link."""
    _ensure_initialized()
    return handle_get_deal_overview(
        query=query, use_llm=use_llm, twenty_client=_twenty_client,
        rules_config=_rules_config, crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_company_overview(
    company_name: Annotated[str, Field(description="Company name (fuzzy match)")],
) -> dict[str, Any]:
    """All open opportunities for a company with health status, issues, and pipeline value."""
    _ensure_initialized()
    return handle_get_company_overview(
        company_name=company_name, twenty_client=_twenty_client,
        rules_config=_rules_config, crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_deal_issues(
    query: Annotated[str, Field(description="Opportunity name or ID")],
) -> dict[str, Any]:
    """Check a single opportunity for hygiene issues. Lighter than get_deal_overview — no action generation."""
    _ensure_initialized()
    return handle_get_deal_issues(
        query=query, twenty_client=_twenty_client,
        rules_config=_rules_config, crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def list_stale_deals(
    min_days: Annotated[int | None, Field(default=None, description="Only show deals stale for at least this many days (post-filter on top of per-stage thresholds)")] = None,
) -> dict[str, Any]:
    """List opportunities past their stale-in-stage threshold."""
    _ensure_initialized()
    return handle_list_stale_deals(
        min_days=min_days, twenty_client=_twenty_client,
        rules_config=_rules_config, crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_audit_history(
    limit: Annotated[int, Field(default=10, ge=1, le=100, description="Number of recent runs to return")] = 10,
) -> dict[str, Any]:
    """Recent pipeline run summaries from the audit log."""
    return handle_get_audit_history(limit=limit)


@mcp.tool(annotations=_READ_ONLY)
def get_run_details(
    run_id: Annotated[str, Field(description="Pipeline run ID")],
) -> dict[str, Any]:
    """Full details for a specific pipeline run: summary, issues, and errors."""
    return handle_get_run_details(run_id=run_id)


@mcp.tool(annotations=_READ_ONLY)
def get_rules_config() -> dict[str, Any]:
    """Show current hygiene rule configuration (thresholds, severities, excluded stages)."""
    return handle_get_rules_config(config_dir=_config_dir)


# --- Resources ---

@mcp.resource("pipelinecoach://config/rules", name="Rules Configuration", description="Current hygiene rules YAML")
def resource_rules_config() -> str:
    rules_path = _config_dir / "rules.yaml"
    return rules_path.read_text() if rules_path.exists() else "# No rules.yaml found"


@mcp.resource("pipelinecoach://config/escalation", name="Escalation Configuration", description="Current escalation YAML")
def resource_escalation_config() -> str:
    esc_path = _config_dir / "escalation.yaml"
    return esc_path.read_text() if esc_path.exists() else "# No escalation.yaml found"


@mcp.resource("pipelinecoach://audit/latest", name="Latest Run Summary", description="Most recent pipeline run summary")
def resource_latest_audit() -> str:
    import json
    from pipeline_coach.mcp.helpers import read_audit_runs

    runs = read_audit_runs(limit=1)
    if not runs:
        return json.dumps({"message": "No runs found"})
    return json.dumps(runs[0], indent=2)
```

- [ ] **Step 2: Verify the server starts**

```bash
echo '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}},"id":1}' | .venv/bin/python -m pipeline_coach.mcp 2>/dev/null | head -1
```

Expected: JSON response with server capabilities

- [ ] **Step 3: Commit**

```bash
git add pipeline_coach/mcp/server.py
git commit -m "feat(mcp): server — FastMCP wiring with 8 tools, 3 resources, stdio transport"
```

---

## Task 5: Docker + README + Final verification

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Add MCP service to docker-compose.yml**

Add after `pipeline-coach-dashboard`:

```yaml
  pipeline-coach-mcp:
    build: .
    depends_on:
      twenty:
        condition: service_healthy
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./data:/app/data
    command: ["python", "-m", "pipeline_coach.mcp"]
    stdin_open: true
```

- [ ] **Step 2: Add MCP section to README.md**

Add a new `## MCP Server` section after Testing:

```markdown
## MCP Server

Pipeline Coach includes an MCP (Model Context Protocol) server for querying pipeline intelligence from AI clients.

### Setup

```bash
pip install -e ".[mcp]"
```

### Claude Code

Add to `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "pipeline-coach": {
      "command": "python",
      "args": ["-m", "pipeline_coach.mcp"],
      "cwd": "/path/to/pipeline-coach",
      "env": {
        "TWENTY_API_URL": "http://localhost:3000",
        "TWENTY_API_KEY": "your-key"
      }
    }
  }
}
```

### Available tools

| Tool | Description |
|---|---|
| `analyze_pipeline` | Run full hygiene analysis on all open opportunities |
| `get_deal_overview` | Deep dive on a single opportunity |
| `get_company_overview` | All deals for a company with health status |
| `get_deal_issues` | Check a single deal for issues (lightweight) |
| `list_stale_deals` | Deals past their stale-in-stage threshold |
| `get_audit_history` | Recent pipeline run summaries |
| `get_run_details` | Full details for a specific run |
| `get_rules_config` | Current rule thresholds and severities |
```

- [ ] **Step 3: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass including new MCP tests

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml README.md
git commit -m "feat(mcp): Docker service, README documentation, and client config example"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `analyze_pipeline` with `use_llm` flag — Task 3 + Task 4
- [x] `get_deal_overview` with fuzzy match + `match_info` + `use_llm` — Task 3 + Task 4
- [x] `get_company_overview` (deterministic only, no `use_llm`) — Task 3 + Task 4
- [x] `get_deal_issues` (lightweight, no actions) — Task 3 + Task 4
- [x] `list_stale_deals` with `min_days` post-filter — Task 3 + Task 4
- [x] `get_audit_history` with `errors` array — Task 3 + Task 4
- [x] `get_run_details` with audit snapshots — Task 3 + Task 4
- [x] `get_rules_config` — Task 3 + Task 4
- [x] Tool annotations (readOnlyHint, idempotentHint) — Task 4
- [x] Resources (pipelinecoach:// scheme) — Task 4
- [x] Fuzzy matching with match_info + other_matches — Task 2
- [x] CRM links using CRM_PUBLIC_URL || TWENTY_API_URL — Task 2
- [x] MCP-specific run_id format (mcp-{uuid}) — Task 2
- [x] stdio transport — Task 1 + Task 4
- [x] mcp as optional extra — Task 1
- [x] Docker Compose service — Task 5
- [x] Security/privacy (trust model) — noted in spec, no code needed for stdio

**Placeholder scan:** No TBD/TODO found. All tool handlers have complete implementations.

**Type consistency:** `fetch_all_contexts` returns `list[OpportunityContext]`. `evaluate_contexts` returns `list[IssueSummary]`. `fuzzy_match_opportunity` returns `tuple[OpportunityContext | None, MatchInfo]`. `handle_*` functions all return `dict[str, Any]`. Consistent across all tasks.
