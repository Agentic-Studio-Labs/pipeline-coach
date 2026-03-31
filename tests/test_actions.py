from __future__ import annotations

from unittest.mock import MagicMock, patch

from pipeline_coach.coach.actions import (
    _get_fallback,
    _get_fallback_rationale,
    _render_summary,
    generate_suggested_action,
    generate_suggested_action_with_rationale,
)
from pipeline_coach.models import Issue, OpportunityContext


def _issue(rule_id: str, severity: str, **details) -> Issue:
    return Issue(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        message=f"issue for {rule_id}",
        details=details,
    )


def _ctx(**kwargs) -> OpportunityContext:
    defaults = dict(
        id="opp-1",
        name="Acme Deal",
        stage="Negotiation",
        owner_email="rep@demo.com",
        amount=50_000.0,
    )
    defaults.update(kwargs)
    return OpportunityContext(**defaults)


class TestFallbackActions:
    def test_close_date_past_contains_close_date(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        result = _get_fallback([issue])
        assert result is not None
        assert "close date" in result.lower()

    def test_stale_in_stage_interpolates_details(self) -> None:
        issue = _issue("stale_in_stage", "medium", stage="Negotiation", days=21)
        result = _get_fallback([issue])
        assert result is not None
        assert "Negotiation" in result
        assert "21" in result

    def test_uses_highest_severity_rule(self) -> None:
        low_issue = _issue("no_recent_activity", "low")
        high_issue = _issue("close_date_past", "high", close_date="2026-01-01")
        result = _get_fallback([low_issue, high_issue])
        # Should use the high-severity close_date_past template
        assert result is not None
        assert "close date" in result.lower()

    def test_empty_issues_returns_none(self) -> None:
        assert _get_fallback([]) is None

    def test_unknown_rule_id_returns_none(self) -> None:
        issue = _issue("unknown_rule", "low")
        result = _get_fallback([issue])
        assert result is None

    def test_missing_details_key_truncates_before_brace(self) -> None:
        # stale_in_stage template has {stage} and {days} — omit them to trigger KeyError
        issue = _issue("stale_in_stage", "medium")  # no details
        result = _get_fallback([issue])
        assert result is not None
        assert "{" not in result

    def test_fallback_rationale_for_known_rule(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        result = _get_fallback_rationale([issue])
        assert result is not None
        assert "forecast" in result.lower() or "risk" in result.lower()


class TestRenderSummary:
    def test_includes_name_and_stage(self) -> None:
        ctx = _ctx(name="Acme Deal", stage="Negotiation")
        summary = _render_summary(ctx)
        assert "Acme Deal" in summary
        assert "Negotiation" in summary

    def test_includes_amount(self) -> None:
        ctx = _ctx(amount=75_000.0)
        summary = _render_summary(ctx)
        assert "75000" in summary or "75,000" in summary

    def test_handles_none_amount(self) -> None:
        ctx = _ctx(amount=None)
        summary = _render_summary(ctx)
        assert summary  # still returns a non-empty string


class TestGenerateSuggestedAction:
    def test_no_issues_returns_none(self) -> None:
        ctx = _ctx()
        result = generate_suggested_action(ctx=ctx, issues=[])
        assert result is None

    def test_deterministic_path_used_by_default(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        ctx = _ctx()
        result = generate_suggested_action(ctx=ctx, issues=[issue])
        assert result is not None
        assert "close date" in result.lower()

    def test_llm_path_calls_predict_action(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        ctx = _ctx()
        mock_pred = MagicMock()
        mock_pred.suggested_action = "Call the account team to confirm the close date."
        with patch(
            "pipeline_coach.coach.actions._predict_action", return_value=mock_pred
        ) as mock_fn:
            result = generate_suggested_action(ctx=ctx, issues=[issue], use_llm=True)
        mock_fn.assert_called_once()
        assert result == "Call the account team to confirm the close date."

    def test_generate_with_rationale_deterministic(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        ctx = _ctx()
        action, rationale = generate_suggested_action_with_rationale(
            ctx=ctx, issues=[issue], use_llm=False
        )
        assert action is not None
        assert rationale is not None
        assert "close date" in action.lower()

    def test_generate_with_rationale_llm(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        ctx = _ctx()
        mock_pred = MagicMock()
        mock_pred.suggested_action = "Call the account team to confirm the close date."
        mock_pred.action_rationale = "This prevents forecast drift on a high-priority deal."

        with patch("pipeline_coach.coach.actions._predict_action", return_value=mock_pred):
            action, rationale = generate_suggested_action_with_rationale(
                ctx=ctx, issues=[issue], use_llm=True
            )

        assert action == "Call the account team to confirm the close date."
        assert rationale == "This prevents forecast drift on a high-priority deal."

    def test_generate_with_rationale_llm_missing_rationale_uses_fallback(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        ctx = _ctx()
        mock_pred = MagicMock()
        mock_pred.suggested_action = "Call the account team to confirm the close date."
        mock_pred.action_rationale = "   "

        with patch("pipeline_coach.coach.actions._predict_action", return_value=mock_pred):
            _, rationale = generate_suggested_action_with_rationale(
                ctx=ctx, issues=[issue], use_llm=True
            )

        assert rationale is not None
        assert "forecast" in rationale.lower() or "risk" in rationale.lower()

    def test_llm_exception_falls_back_to_deterministic(self) -> None:
        issue = _issue("close_date_past", "high", close_date="2026-01-01")
        ctx = _ctx()
        with patch(
            "pipeline_coach.coach.actions._predict_action",
            side_effect=Exception("LLM unavailable"),
        ):
            result = generate_suggested_action(ctx=ctx, issues=[issue], use_llm=True)
        assert result is not None
        assert "close date" in result.lower()
