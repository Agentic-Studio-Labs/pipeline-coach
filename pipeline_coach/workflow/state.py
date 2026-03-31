from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from pipeline_coach.models import Brief, IssueSummary, OpportunityContext


class PipelineState(TypedDict):
    companies: list[dict]
    people: list[dict]
    opportunities: list[dict]
    tasks: list[dict]
    workspace_members: list[dict]
    contexts: list[OpportunityContext]
    validated_summaries: list[IssueSummary]
    pending_summaries: list[IssueSummary]
    ae_briefs: dict[str, Brief]
    escalation_briefs: dict[str, Brief]
    action_retry_count_by_opp: dict[str, int]
    run_id: str
    emails_sent: int
    emails_failed: int
    errors: Annotated[list[str], add]
