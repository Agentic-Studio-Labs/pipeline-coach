from __future__ import annotations

import logging

import dspy

from pipeline_coach.models import SEVERITY_RANK, Issue, OpportunityContext

logger = logging.getLogger(__name__)

FALLBACK_ACTIONS: dict[str, str] = {
    "stale_in_stage": (
        "Review this deal — it's been in {stage} for {days} days."
        " Update the stage or add a next step."
    ),
    "no_recent_activity": "Log your latest interaction or schedule a follow-up.",
    "close_date_past": "Update the close date — the current one has passed.",
    "close_date_soon_no_activity": (
        "Close date is in {days_until_close} days with no recent activity."
        " Confirm timing or push the date."
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
    amount_str = f"${ctx.amount:,.0f}" if ctx.amount is not None else "N/A"
    close_str = str(ctx.close_date) if ctx.close_date is not None else "N/A"
    return f"{ctx.name} — Stage: {ctx.stage} | Amount: {amount_str} | Close: {close_str}"


def _get_fallback(issues: list[Issue]) -> str | None:
    if not issues:
        return None

    best = max(issues, key=lambda i: SEVERITY_RANK.get(i.severity, 0))
    template = FALLBACK_ACTIONS.get(best.rule_id)
    if template is None:
        return None

    try:
        return template.format(**best.details)
    except KeyError:
        brace_pos = template.find("{")
        return template[:brace_pos].rstrip(" —,")


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
    issues_text = "; ".join(i.message for i in issues)
    try:
        prediction = _predict_action(summary, issues_text)
        return prediction.suggested_action.strip()
    except Exception:
        logger.warning("DSPy prediction failed; falling back to deterministic action")
        return _get_fallback(issues)
