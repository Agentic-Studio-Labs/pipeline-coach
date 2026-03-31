from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from pipeline_coach.coach.actions import generate_suggested_action_with_rationale
from pipeline_coach.config import RulesConfig
from pipeline_coach.hygiene.rules import evaluate_opportunity
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


def handle_analyze_pipeline(
    *,
    use_llm: bool,
    twenty_client: Any,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    if today is None:
        today = date.today()

    contexts = fetch_all_contexts(twenty_client, rules_config, today=today)
    summaries = evaluate_contexts(contexts, rules_config, today=today)
    run_id = generate_mcp_run_id()

    result_summaries: list[dict[str, Any]] = []
    for s in summaries:
        action, rationale = generate_suggested_action_with_rationale(
            ctx=s.context,
            issues=s.issues,
            use_llm=use_llm,
        )
        result_summaries.append(
            {
                "opportunity_id": s.opportunity_id,
                "opportunity_name": s.opportunity_name,
                "owner_email": s.owner_email,
                "priority": s.priority,
                "issues": [i.model_dump() for i in s.issues],
                "suggested_action": action,
                "action_rationale": rationale,
                "crm_link": build_crm_link(s.opportunity_id, crm_url=crm_url),
            }
        )

    return {
        "run_id": run_id,
        "total_opportunities": len(contexts),
        "issues_found": len(summaries),
        "summaries": result_summaries,
    }


def handle_get_deal_overview(
    *,
    query: str,
    use_llm: bool,
    twenty_client: Any,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    if today is None:
        today = date.today()

    contexts = fetch_all_contexts(twenty_client, rules_config, today=today)
    opp, match_info = fuzzy_match_opportunity(query, contexts)

    if opp is None:
        return {"error": "No matching opportunity found", "match_info": dict(match_info)}

    issues = evaluate_opportunity(opp, rules_config, today=today)
    action, rationale = generate_suggested_action_with_rationale(
        ctx=opp,
        issues=issues,
        use_llm=use_llm,
    )

    return {
        "opportunity": opp.model_dump(mode="json"),
        "match_info": dict(match_info),
        "crm_link": build_crm_link(opp.id, crm_url=crm_url),
        "issues": [i.model_dump() for i in issues],
        "suggested_action": action,
        "action_rationale": rationale,
    }


def handle_get_company_overview(
    *,
    company_name: str,
    twenty_client: Any,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    if today is None:
        today = date.today()

    contexts = fetch_all_contexts(twenty_client, rules_config, today=today)
    matched_contexts, match_info = fuzzy_match_company(company_name, contexts)

    if not matched_contexts:
        return {
            "error": "No matching company found",
            "match_info": dict(match_info),
        }

    deals: list[dict[str, Any]] = []
    for ctx in matched_contexts:
        issues = evaluate_opportunity(ctx, rules_config, today=today)
        deals.append(
            {
                "name": ctx.name,
                "opportunity_id": ctx.id,
                "stage": ctx.stage,
                "amount": ctx.amount,
                "close_date": str(ctx.close_date) if ctx.close_date else None,
                "issues": [i.model_dump() for i in issues],
                "crm_link": build_crm_link(ctx.id, crm_url=crm_url),
            }
        )

    return {
        "company_name": match_info["matched_name"],
        "match_info": dict(match_info),
        "total_deals": len(deals),
        "deals": deals,
    }


def handle_get_deal_issues(
    *,
    query: str,
    twenty_client: Any,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    if today is None:
        today = date.today()

    contexts = fetch_all_contexts(twenty_client, rules_config, today=today)
    opp, match_info = fuzzy_match_opportunity(query, contexts)

    if opp is None:
        return {"error": "No matching opportunity found", "match_info": dict(match_info)}

    issues = evaluate_opportunity(opp, rules_config, today=today)

    return {
        "opportunity_id": opp.id,
        "opportunity_name": opp.name,
        "match_info": dict(match_info),
        "crm_link": build_crm_link(opp.id, crm_url=crm_url),
        "issues": [i.model_dump() for i in issues],
    }


def handle_list_stale_deals(
    *,
    min_days: int | None,
    twenty_client: Any,
    rules_config: RulesConfig,
    crm_url: str,
    today: date | None = None,
) -> dict[str, Any]:
    if today is None:
        today = date.today()

    contexts = fetch_all_contexts(twenty_client, rules_config, today=today)
    sis = rules_config.stale_in_stage

    stale_deals: list[dict[str, Any]] = []
    for ctx in contexts:
        if not sis.enabled or ctx.days_in_stage is None:
            continue

        threshold = sis.by_stage.get(ctx.stage, sis.default_days)
        if ctx.days_in_stage <= threshold:
            continue

        if min_days is not None and ctx.days_in_stage < min_days:
            continue

        stale_deals.append(
            {
                "opportunity_id": ctx.id,
                "opportunity_name": ctx.name,
                "stage": ctx.stage,
                "days_in_stage": ctx.days_in_stage,
                "threshold": threshold,
                "crm_link": build_crm_link(ctx.id, crm_url=crm_url),
            }
        )

    return {
        "total_stale": len(stale_deals),
        "stale_deals": stale_deals,
    }


def handle_get_audit_history(
    *,
    limit: int = 10,
    audit_dir: Path | None = None,
) -> dict[str, Any]:
    runs = read_audit_runs(audit_dir=audit_dir, limit=limit)
    return {"runs": runs, "total": len(runs)}


def handle_get_run_details(
    *,
    run_id: str,
    audit_dir: Path | None = None,
) -> dict[str, Any]:
    run_record, issues = read_run_issues(run_id=run_id, audit_dir=audit_dir)

    if run_record is None:
        return {"error": f"Run {run_id} not found"}

    return {
        "run": run_record,
        "issues": issues,
        "total_issues": len(issues),
    }


def handle_get_rules_config(
    *,
    config_dir: Path | None = None,
) -> dict[str, Any]:
    if config_dir is None:
        config_dir = Path("config")

    rules_path = config_dir / "rules.yaml"

    try:
        data = yaml.safe_load(rules_path.read_text())
    except FileNotFoundError:
        return {"error": f"Rules file not found: {rules_path}"}

    return {
        "excluded_stages": data.get("excluded_stages", []),
        "rules": data.get("rules", {}),
    }
