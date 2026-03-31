from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pipeline_coach.models import OpportunityContext


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(raw: str | None) -> date | None:
    dt = _parse_dt(raw) if raw and "T" in raw else None
    if dt is not None:
        return dt.date()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _extract_amount(raw: dict | None) -> float | None:
    if raw is None:
        return None
    micros = raw.get("amountMicros")
    if micros is None:
        return None
    return int(micros) / 1_000_000


def _full_name(raw: dict | None) -> str | None:
    if raw is None:
        return None
    first = raw.get("firstName") or ""
    last = raw.get("lastName") or ""
    name = f"{first} {last}".strip()
    return name if name else None


def normalize_opportunities(
    *,
    opportunities: list[dict],
    companies: list[dict],
    people: list[dict],
    workspace_members: list[dict],
    tasks: list[dict],
    today: date,
    excluded_stages: list[str] | None = None,
) -> list[OpportunityContext]:
    excluded = set(excluded_stages) if excluded_stages else set()

    company_map: dict[str, str] = {c["id"]: c["name"] for c in companies}

    member_map: dict[str, dict[str, Any]] = {}
    for m in workspace_members:
        member_map[m["id"]] = {
            "email": m.get("userEmail", ""),
            "name": _full_name(m.get("name")),
        }

    poc_set: set[str] = {p["id"] for p in people}

    opp_latest_activity: dict[str, datetime] = {}
    for task in tasks:
        completed_raw = task.get("completedAt")
        task_dt = _parse_dt(completed_raw)
        if task_dt is None:
            continue
        edges = task.get("taskTargets", {}).get("edges", [])
        for edge in edges:
            node = edge.get("node", {})
            opp_id = node.get("targetOpportunityId") or node.get("opportunityId")
            if not opp_id:
                continue
            existing = opp_latest_activity.get(opp_id)
            if existing is None or task_dt > existing:
                opp_latest_activity[opp_id] = task_dt

    result: list[OpportunityContext] = []
    for opp in opportunities:
        stage = opp.get("stage", "")
        if stage in excluded:
            continue

        opp_id = opp["id"]
        owner_id = opp.get("ownerId")
        member = member_map.get(owner_id) if owner_id else None
        owner_email = member["email"] if member else "unknown@unknown.com"
        owner_name = member["name"] if member else None

        company_id = opp.get("companyId")
        company_name = company_map.get(company_id) if company_id else None

        amount = _extract_amount(opp.get("amount"))
        close_date = _parse_date(opp.get("closeDate"))

        stage_changed_raw = opp.get("stageChangedAt")
        updated_raw = opp.get("updatedAt")
        stage_dt = _parse_dt(stage_changed_raw) or _parse_dt(updated_raw)
        days_in_stage = (today - stage_dt.date()).days if stage_dt else None

        last_activity_at = opp_latest_activity.get(opp_id)
        days_since_last_activity = (
            (today - last_activity_at.date()).days if last_activity_at else None
        )

        poc_id = opp.get("pointOfContactId")
        has_decision_maker = poc_id in poc_set if poc_id is not None else False

        result.append(
            OpportunityContext(
                id=opp_id,
                name=opp.get("name", ""),
                amount=amount,
                stage=stage,
                owner_email=owner_email,
                owner_name=owner_name,
                company_name=company_name,
                close_date=close_date,
                last_activity_at=last_activity_at,
                days_in_stage=days_in_stage,
                days_since_last_activity=days_since_last_activity,
                has_decision_maker=has_decision_maker,
            )
        )

    return result
