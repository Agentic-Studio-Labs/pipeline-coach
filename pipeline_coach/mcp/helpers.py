from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

from pipeline_coach.config import AppConfig, RulesConfig
from pipeline_coach.hygiene.priority import compute_priority
from pipeline_coach.hygiene.rules import evaluate_opportunity
from pipeline_coach.ingestion.normalizer import normalize_opportunities
from pipeline_coach.models import IssueSummary, OpportunityContext

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class MatchInfo(TypedDict):
    matched_name: str | None
    match_type: str
    other_matches: list[str]


# ---------------------------------------------------------------------------
# CRM URL helpers
# ---------------------------------------------------------------------------


def get_crm_url(app_config: AppConfig) -> str:
    return app_config.crm_public_url or app_config.twenty_api_url


def build_crm_link(opp_id: str, *, crm_url: str) -> str:
    base = crm_url.rstrip("/")
    return f"{base}/object/opportunity/{opp_id}"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

_OPP_FIELDS = (
    "id name amount { amountMicros currencyCode } stage closeDate "
    "createdAt updatedAt stageChangedAt companyId pointOfContactId ownerId"
)
_COMPANY_FIELDS = "id name"
_PERSON_FIELDS = "id name { firstName lastName } emails { primaryEmail } companyId jobTitle"
_MEMBER_FIELDS = "id name { firstName lastName } userEmail"
_TASK_FIELDS = (
    "id createdAt updatedAt status taskTargets { edges { node { targetOpportunityId } } }"
)


def fetch_all_contexts(
    twenty_client: Any,
    rules_config: RulesConfig,
    today: date | None = None,
) -> list[OpportunityContext]:
    if today is None:
        today = date.today()

    opportunities = twenty_client.fetch_all("opportunities", _OPP_FIELDS)
    companies = twenty_client.fetch_all("companies", _COMPANY_FIELDS)
    people = twenty_client.fetch_all("people", _PERSON_FIELDS)
    workspace_members = twenty_client.fetch_all("workspaceMembers", _MEMBER_FIELDS)
    tasks = twenty_client.fetch_all("tasks", _TASK_FIELDS)

    return normalize_opportunities(
        opportunities=opportunities,
        companies=companies,
        people=people,
        workspace_members=workspace_members,
        tasks=tasks,
        today=today,
        excluded_stages=rules_config.excluded_stages,
    )


# ---------------------------------------------------------------------------
# Issue evaluation
# ---------------------------------------------------------------------------


def evaluate_contexts(
    contexts: list[OpportunityContext],
    rules_config: RulesConfig,
    today: date | None = None,
) -> list[IssueSummary]:
    if today is None:
        today = date.today()

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


# ---------------------------------------------------------------------------
# Fuzzy matching — opportunity
# ---------------------------------------------------------------------------


def fuzzy_match_opportunity(
    query: str, contexts: list[OpportunityContext]
) -> tuple[OpportunityContext | None, MatchInfo]:
    query_lower = query.lower()

    # 1. UUID / ID match (case-insensitive)
    for ctx in contexts:
        if ctx.id.lower() == query_lower:
            return ctx, MatchInfo(
                matched_name=ctx.name,
                match_type="uuid",
                other_matches=[],
            )

    # 2. Exact name match (case-insensitive)
    exact = [ctx for ctx in contexts if ctx.name.lower() == query_lower]
    if exact:
        first = exact[0]
        others = [c.name for c in exact[1:]]
        return first, MatchInfo(
            matched_name=first.name,
            match_type="exact_name",
            other_matches=others,
        )

    # 3. Substring match (case-insensitive)
    subs = [ctx for ctx in contexts if query_lower in ctx.name.lower()]
    if subs:
        first = subs[0]
        others = [c.name for c in subs[1:]]
        return first, MatchInfo(
            matched_name=first.name,
            match_type="substring",
            other_matches=others,
        )

    return None, MatchInfo(matched_name=None, match_type="none", other_matches=[])


# ---------------------------------------------------------------------------
# Fuzzy matching — company
# ---------------------------------------------------------------------------


def fuzzy_match_company(
    company_name: str, contexts: list[OpportunityContext]
) -> tuple[list[OpportunityContext], MatchInfo]:
    query_lower = company_name.lower()

    # 1. Exact match (case-insensitive)
    exact = [
        ctx for ctx in contexts if ctx.company_name and ctx.company_name.lower() == query_lower
    ]
    if exact:
        return exact, MatchInfo(
            matched_name=exact[0].company_name,
            match_type="exact",
            other_matches=[],
        )

    # 2. Substring match (case-insensitive)
    subs = [
        ctx for ctx in contexts if ctx.company_name and query_lower in ctx.company_name.lower()
    ]
    if subs:
        return subs, MatchInfo(
            matched_name=subs[0].company_name,
            match_type="substring",
            other_matches=[],
        )

    return [], MatchInfo(matched_name=None, match_type="none", other_matches=[])


# ---------------------------------------------------------------------------
# Audit log readers
# ---------------------------------------------------------------------------

_DEFAULT_AUDIT_DIR = Path("data")


def _audit_path(audit_dir: Path | None) -> Path:
    base = audit_dir if audit_dir is not None else _DEFAULT_AUDIT_DIR
    return base / "audit_log.jsonl"


def read_audit_runs(*, audit_dir: Path | None = None, limit: int = 10) -> list[dict]:
    path = _audit_path(audit_dir)
    if not path.exists():
        return []

    runs: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "run":
                runs.append(record)

    # Return the most recent `limit` runs (last N from file)
    return runs[-limit:]


def read_run_issues(
    *, run_id: str, audit_dir: Path | None = None
) -> tuple[dict | None, list[dict]]:
    path = _audit_path(audit_dir)
    if not path.exists():
        return None, []

    run_record: dict | None = None
    issues: list[dict] = []

    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("run_id") != run_id:
                continue
            if record.get("type") == "run":
                run_record = record
            elif record.get("type") == "issue":
                issues.append(record)

    return run_record, issues


# ---------------------------------------------------------------------------
# Run ID generation
# ---------------------------------------------------------------------------


def generate_mcp_run_id() -> str:
    return f"mcp-{uuid.uuid4().hex[:8]}"
