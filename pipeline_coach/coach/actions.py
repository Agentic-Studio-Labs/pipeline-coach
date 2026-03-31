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

FALLBACK_RATIONALES: dict[str, str] = {
    "stale_in_stage": "This deal may be losing momentum, which increases close risk.",
    "no_recent_activity": "No recent activity is a leading indicator of pipeline slippage.",
    "close_date_past": "Past close dates reduce forecast accuracy and hide true pipeline health.",
    "close_date_soon_no_activity": "A near-term close with no activity suggests execution risk.",
    "missing_amount": "Missing amount weakens forecast quality and prioritization.",
    "missing_close_date": "Missing close date prevents realistic planning and forecast timing.",
    "missing_decision_maker": "Lack of decision maker access can block deal progression.",
}


class SuggestActionSig(dspy.Signature):
    """Given an opportunity summary and its hygiene issues, propose one concise, practical next action for the AE."""

    opportunity_summary: str = dspy.InputField()
    issues: str = dspy.InputField()
    suggested_action: str = dspy.OutputField(
        desc="One concise, practical next best action for the AE. Be specific — name the action, not the problem."
    )
    action_rationale: str = dspy.OutputField(
        desc="One short sentence explaining why this action matters now."
    )


_predictor: dspy.Predict | None = None


def _get_predictor() -> dspy.Predict:
    global _predictor  # noqa: PLW0603
    if _predictor is None:
        _predictor = dspy.Predict(SuggestActionSig)
    return _predictor


def _predict_action(summary: str, issues_text: str) -> dspy.Prediction:
    return _get_predictor()(
        opportunity_summary=summary,
        issues=issues_text,
    )


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


def _get_fallback_rationale(issues: list[Issue]) -> str | None:
    if not issues:
        return None

    best = max(issues, key=lambda i: SEVERITY_RANK.get(i.severity, 0))
    return FALLBACK_RATIONALES.get(
        best.rule_id, "Addressing this now reduces near-term pipeline risk."
    )


def _clean_sentence(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return None
    return cleaned


def generate_suggested_action_with_rationale(
    *,
    ctx: OpportunityContext,
    issues: list[Issue],
    use_llm: bool = False,
) -> tuple[str | None, str | None]:
    if not issues:
        return None, None

    if not use_llm:
        return _get_fallback(issues), _get_fallback_rationale(issues)

    summary = _render_summary(ctx)
    issues_text = "; ".join(i.message for i in issues)
    try:
        prediction = _predict_action(summary, issues_text)
        action = _clean_sentence(getattr(prediction, "suggested_action", None))
        if action is None:
            raise ValueError("LLM returned empty suggested_action")

        rationale = _clean_sentence(getattr(prediction, "action_rationale", None))
        if rationale is None:
            rationale = _get_fallback_rationale(issues)
        return action, rationale
    except Exception:
        logger.warning(
            "DSPy prediction failed; falling back to deterministic action", exc_info=True
        )
        return _get_fallback(issues), _get_fallback_rationale(issues)


def generate_suggested_action(
    *,
    ctx: OpportunityContext,
    issues: list[Issue],
    use_llm: bool = False,
) -> str | None:
    action, _ = generate_suggested_action_with_rationale(
        ctx=ctx,
        issues=issues,
        use_llm=use_llm,
    )
    return action
