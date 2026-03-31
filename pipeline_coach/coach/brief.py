from __future__ import annotations

from datetime import date

from pipeline_coach.models import Brief, IssueSummary


def _format_amount(amount: float | None) -> str:
    if amount is None:
        return "Not set"
    return f"${amount:,.0f}"


def _format_date(d: date | None, today: date) -> str:
    if d is None:
        return "Not set"
    suffix = " (PAST)" if d < today else ""
    return f"{d}{suffix}"


def _opp_link(crm_url: str | None, opp_id: str) -> str:
    if not crm_url:
        return ""
    return f"\n   View: {crm_url.rstrip('/')}/object/opportunity/{opp_id}"


def render_ae_brief(
    owner_name: str | None,
    summaries: list[IssueSummary],
    *,
    today: date | None = None,
    crm_url: str | None = None,
) -> Brief:
    today = today or date.today()
    greeting = f"Hi {owner_name}" if owner_name else "Hi"

    lines: list[str] = [
        f"{greeting},",
        "",
        "Here are your pipeline items that need attention today:",
        "",
    ]

    for i, s in enumerate(summaries, start=1):
        ctx = s.context
        last_activity = ctx.last_activity_at.date() if ctx.last_activity_at is not None else None
        lines.append(f"{i}. {s.opportunity_name} ({ctx.company_name or 'Unknown company'})")
        lines.append(
            f"   Amount: {_format_amount(ctx.amount)} | "
            f"Last activity: {_format_date(last_activity, today)} | "
            f"Close date: {_format_date(ctx.close_date, today)}"
        )
        for issue in s.issues:
            lines.append(f"   - {issue.message}")
        if s.suggested_action:
            lines.append(f"   Suggested action: {s.suggested_action}")
        if s.action_rationale:
            lines.append(f"   Why now: {s.action_rationale}")
        link = _opp_link(crm_url, s.opportunity_id)
        if link:
            lines.append(link)
        lines.append("")

    lines.append("Pipeline Coach")

    return Brief(
        subject=f"Your Pipeline Coach brief for {today}",
        body="\n".join(lines),
    )


def render_escalation_brief(
    *,
    manager_name: str | None,
    ae_name: str,
    ae_email: str,
    summaries: list[IssueSummary],
    today: date | None = None,
    crm_url: str | None = None,
) -> Brief:
    today = today or date.today()
    n = len(summaries)
    greeting = f"Hi {manager_name}" if manager_name else "Hi"

    lines: list[str] = [
        f"{greeting},",
        "",
        f"The following {n} deal(s) owned by {ae_name} ({ae_email}) require your attention:",
        "",
    ]

    for i, s in enumerate(summaries, start=1):
        lines.append(f"{i}. {s.opportunity_name}")
        for issue in s.issues:
            lines.append(f"   - {issue.message}")
        lines.append(f"   AE: {ae_name} <{ae_email}>")
        link = _opp_link(crm_url, s.opportunity_id)
        if link:
            lines.append(link)
        lines.append("")

    lines.append("Pipeline Coach")

    return Brief(
        subject=f"[Escalation] {n} critical deal(s) need attention — {today}",
        body="\n".join(lines),
    )
