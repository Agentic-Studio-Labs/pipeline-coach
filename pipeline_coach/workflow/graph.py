from __future__ import annotations

import logging
from datetime import date
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from pipeline_coach.coach.actions import generate_suggested_action
from pipeline_coach.coach.brief import render_ae_brief, render_escalation_brief
from pipeline_coach.coach.quality_gate import validate_action
from pipeline_coach.config import EscalationConfig, RulesConfig
from pipeline_coach.delivery.router import route_summaries
from pipeline_coach.hygiene.priority import compute_priority
from pipeline_coach.hygiene.rules import evaluate_opportunity
from pipeline_coach.ingestion.normalizer import normalize_opportunities
from pipeline_coach.models import IssueSummary
from pipeline_coach.workflow.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node functions — all module-level, config bound via functools.partial
# ---------------------------------------------------------------------------


def fetch_companies(state: PipelineState, *, twenty_client: Any) -> dict:
    try:
        data = twenty_client.fetch_all("companies", "id name")
        return {"companies": data}
    except Exception as exc:
        return {"companies": [], "errors": [f"fetch_companies failed: {exc}"]}


def fetch_people(state: PipelineState, *, twenty_client: Any) -> dict:
    try:
        data = twenty_client.fetch_all(
            "people",
            "id name { firstName lastName } emails { primaryEmail } companyId jobTitle",
        )
        return {"people": data}
    except Exception as exc:
        return {"people": [], "errors": [f"fetch_people failed: {exc}"]}


def fetch_opportunities(state: PipelineState, *, twenty_client: Any) -> dict:
    try:
        data = twenty_client.fetch_all(
            "opportunities",
            "id name amount { amountMicros currencyCode } stage closeDate "
            "createdAt updatedAt stageChangedAt companyId pointOfContactId ownerId",
        )
        return {"opportunities": data}
    except Exception as exc:
        return {"opportunities": [], "errors": [f"fetch_opportunities failed: {exc}"]}


def fetch_tasks(state: PipelineState, *, twenty_client: Any) -> dict:
    try:
        data = twenty_client.fetch_all(
            "tasks",
            "id createdAt status taskTargets { edges { node { targetOpportunityId } } }",
        )
        return {"tasks": data}
    except Exception as exc:
        return {"tasks": [], "errors": [f"fetch_tasks failed: {exc}"]}


def fetch_workspace_members(state: PipelineState, *, twenty_client: Any) -> dict:
    try:
        data = twenty_client.fetch_all(
            "workspaceMembers",
            "id name { firstName lastName } userEmail",
        )
        return {"workspace_members": data}
    except Exception as exc:
        return {"workspace_members": [], "errors": [f"fetch_workspace_members failed: {exc}"]}


def join_data(
    state: PipelineState,
    *,
    today: date,
    excluded_stages: list[str] | None = None,
) -> dict:
    contexts = normalize_opportunities(
        opportunities=state["opportunities"],
        companies=state["companies"],
        people=state["people"],
        workspace_members=state["workspace_members"],
        tasks=state["tasks"],
        today=today,
        excluded_stages=excluded_stages,
    )
    return {"contexts": contexts}


def compute_issues(
    state: PipelineState,
    *,
    rules_config: RulesConfig,
    today: date,
) -> dict:
    pending: list[IssueSummary] = []
    for ctx in state["contexts"]:
        issues = evaluate_opportunity(ctx, rules_config, today=today)
        if not issues:
            continue
        priority = compute_priority(issues, amount=ctx.amount, stage=ctx.stage)
        pending.append(
            IssueSummary(
                opportunity_id=ctx.id,
                opportunity_name=ctx.name,
                owner_email=ctx.owner_email,
                priority=priority,
                issues=issues,
                context=ctx,
            )
        )
    return {"pending_summaries": pending, "validated_summaries": []}


def generate_actions(state: PipelineState, *, use_llm: bool) -> dict:
    updated: list[IssueSummary] = []
    for summary in state["pending_summaries"]:
        if summary.suggested_action is not None:
            updated.append(summary)
            continue
        action = generate_suggested_action(
            ctx=summary.context,
            issues=summary.issues,
            use_llm=use_llm,
        )
        updated.append(summary.model_copy(update={"suggested_action": action}))
    return {"pending_summaries": updated}


def validate_actions(
    state: PipelineState,
    *,
    use_llm: bool,
    max_retries: int = 2,
) -> dict:
    validated = list(state["validated_summaries"])
    still_pending: list[IssueSummary] = []
    retry_counts = dict(state["action_retry_count_by_opp"])

    for summary in state["pending_summaries"]:
        issues_text = "\n".join(f"- {issue.message}" for issue in summary.issues)
        passed = validate_action(summary.suggested_action, issues_text=issues_text)

        if passed:
            validated.append(summary)
        else:
            current_retries = retry_counts.get(summary.opportunity_id, 0)
            if current_retries < max_retries and use_llm:
                retry_counts[summary.opportunity_id] = current_retries + 1
                still_pending.append(summary.model_copy(update={"suggested_action": None}))
            else:
                # Exhausted retries or no LLM — use fallback action as-is
                validated.append(summary)

    return {
        "validated_summaries": validated,
        "pending_summaries": still_pending,
        "action_retry_count_by_opp": retry_counts,
    }


def should_retry_actions(state: PipelineState) -> str:
    if state["pending_summaries"]:
        return "generate_actions"
    return "route_by_severity"


def route_by_severity(
    state: PipelineState,
    *,
    escalation_config: EscalationConfig,
    today: date,
    crm_url: str | None = None,
) -> dict:
    routing = route_summaries(state["validated_summaries"], escalation_config)

    ae_briefs: dict[str, Any] = {}
    for owner_email, summaries in routing.ae_briefs.items():
        owner_name = summaries[0].context.owner_name if summaries else None
        ae_briefs[owner_email] = render_ae_brief(
            owner_name,
            summaries,
            today=today,
            crm_url=crm_url,
        )

    escalation_briefs: dict[str, Any] = {}
    for manager_email, summaries in routing.escalations.items():
        first = summaries[0]
        ae_name = first.context.owner_name or first.owner_email
        ae_email = first.owner_email
        escalation_briefs[manager_email] = render_escalation_brief(
            manager_name=None,
            ae_name=ae_name,
            ae_email=ae_email,
            summaries=summaries,
            today=today,
            crm_url=crm_url,
        )

    return {"ae_briefs": ae_briefs, "escalation_briefs": escalation_briefs}


def send_emails(state: PipelineState, *, email_client: Any) -> dict:
    sent = 0
    failed = 0

    for recipient, brief in state["ae_briefs"].items():
        result = email_client.send(to=recipient, subject=brief.subject, body=brief.body)
        if result is not None:
            sent += 1
        else:
            failed += 1

    for recipient, brief in state["escalation_briefs"].items():
        result = email_client.send(to=recipient, subject=brief.subject, body=brief.body)
        if result is not None:
            sent += 1
        else:
            failed += 1

    return {"emails_sent": sent, "emails_failed": failed}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(
    *,
    twenty_client: Any,
    email_client: Any,
    rules_config: RulesConfig,
    escalation_config: EscalationConfig,
    use_llm: bool = False,
    today: date | None = None,
    excluded_stages: list[str] | None = None,
    crm_url: str | None = None,
) -> StateGraph:
    today = today or date.today()

    graph = StateGraph(PipelineState)

    # Add nodes with config bound via partial
    graph.add_node("fetch_companies", partial(fetch_companies, twenty_client=twenty_client))
    graph.add_node("fetch_people", partial(fetch_people, twenty_client=twenty_client))
    graph.add_node(
        "fetch_opportunities", partial(fetch_opportunities, twenty_client=twenty_client)
    )
    graph.add_node("fetch_tasks", partial(fetch_tasks, twenty_client=twenty_client))
    graph.add_node(
        "fetch_workspace_members",
        partial(fetch_workspace_members, twenty_client=twenty_client),
    )
    graph.add_node("join_data", partial(join_data, today=today, excluded_stages=excluded_stages))
    graph.add_node(
        "compute_issues", partial(compute_issues, rules_config=rules_config, today=today)
    )
    graph.add_node("generate_actions", partial(generate_actions, use_llm=use_llm))
    graph.add_node("validate_actions", partial(validate_actions, use_llm=use_llm))
    graph.add_node(
        "route_by_severity",
        partial(
            route_by_severity, escalation_config=escalation_config, today=today, crm_url=crm_url
        ),
    )
    graph.add_node("send_emails", partial(send_emails, email_client=email_client))

    # Fan-out from START to all fetch nodes
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

    # Sequential pipeline
    graph.add_edge("join_data", "compute_issues")
    graph.add_edge("compute_issues", "generate_actions")
    graph.add_edge("generate_actions", "validate_actions")

    # Conditional retry loop
    graph.add_conditional_edges(
        "validate_actions",
        should_retry_actions,
        {"generate_actions": "generate_actions", "route_by_severity": "route_by_severity"},
    )

    graph.add_edge("route_by_severity", "send_emails")
    graph.add_edge("send_emails", END)

    return graph.compile()
