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
    if today is None:
        today = date.today()

    issues: list[Issue] = []

    # 1. stale_in_stage
    sis = rules_config.stale_in_stage
    if sis.enabled and ctx.days_in_stage is not None:
        threshold = sis.by_stage.get(ctx.stage, sis.default_days)
        if ctx.days_in_stage > threshold:
            issues.append(
                Issue(
                    rule_id="stale_in_stage",
                    severity=sis.severity,
                    message=f"Stale in {ctx.stage}: {ctx.days_in_stage} days (threshold: {threshold})",
                    details={
                        "stage": ctx.stage,
                        "days": ctx.days_in_stage,
                        "threshold": threshold,
                    },
                )
            )

    # 2. no_recent_activity
    nra = rules_config.no_recent_activity
    if nra.enabled and ctx.days_since_last_activity is not None:
        if ctx.days_since_last_activity > nra.days:
            issues.append(
                Issue(
                    rule_id="no_recent_activity",
                    severity=nra.severity,
                    message=f"No activity in {ctx.days_since_last_activity} days (threshold: {nra.days})",
                    details={"days": ctx.days_since_last_activity, "threshold": nra.days},
                )
            )

    # 3. close_date_past
    cdp = rules_config.close_date_past
    if cdp.enabled and ctx.close_date is not None:
        if ctx.close_date < today:
            issues.append(
                Issue(
                    rule_id="close_date_past",
                    severity="high",
                    message=f"Close date {ctx.close_date} is in the past",
                    details={"close_date": str(ctx.close_date)},
                )
            )

    # 4. close_date_soon_no_activity
    cdsa = rules_config.close_date_soon_no_activity
    if cdsa.enabled and ctx.close_date is not None and ctx.days_since_last_activity is not None:
        days_until_close = (ctx.close_date - today).days
        if (
            0 <= days_until_close <= cdsa.close_date_soon_days
            and ctx.days_since_last_activity > cdsa.no_activity_days
        ):
            issues.append(
                Issue(
                    rule_id="close_date_soon_no_activity",
                    severity=cdsa.severity,
                    message=(
                        f"Close date in {days_until_close} days but no activity "
                        f"in {ctx.days_since_last_activity} days"
                    ),
                    details={
                        "days_until_close": days_until_close,
                        "days_since_last_activity": ctx.days_since_last_activity,
                    },
                )
            )

    # 5. missing_amount
    ma = rules_config.missing_amount
    if ma.enabled and (ctx.amount is None or ctx.amount == 0.0):
        issues.append(
            Issue(
                rule_id="missing_amount",
                severity=ma.severity,
                message="Opportunity amount is missing or zero",
                details={},
            )
        )

    # 6. missing_close_date
    mcd = rules_config.missing_close_date
    if mcd.enabled and ctx.close_date is None:
        issues.append(
            Issue(
                rule_id="missing_close_date",
                severity=mcd.severity,
                message="Close date is not set",
                details={},
            )
        )

    # 7. missing_decision_maker
    mdm = rules_config.missing_decision_maker
    if mdm.enabled and ctx.stage in mdm.by_stage and ctx.has_decision_maker is False:
        issues.append(
            Issue(
                rule_id="missing_decision_maker",
                severity=mdm.severity,
                message=f"No decision maker identified for stage: {ctx.stage}",
                details={"stage": ctx.stage},
            )
        )

    return issues
