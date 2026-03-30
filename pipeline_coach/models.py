from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SEVERITY_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}


class OpportunityContext(BaseModel):
    id: str
    name: str
    amount: float | None = None
    stage: str
    owner_email: str
    owner_name: str | None = None
    company_name: str | None = None
    close_date: date | None = None
    last_activity_at: datetime | None = None
    days_in_stage: int | None = None
    days_since_last_activity: int | None = None
    has_decision_maker: bool | None = None


class Issue(BaseModel):
    rule_id: str
    severity: Literal["high", "medium", "low"]
    message: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class IssueSummary(BaseModel):
    opportunity_id: str
    opportunity_name: str
    owner_email: str
    priority: Literal["high", "medium", "low"]
    issues: list[Issue]
    context: OpportunityContext
    suggested_action: str | None = None


@dataclass(frozen=True)
class Brief:
    subject: str
    body: str
