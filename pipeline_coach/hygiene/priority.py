from __future__ import annotations

from typing import Literal

from pipeline_coach.models import SEVERITY_RANK, Issue


def compute_priority(
    issues: list[Issue],
    amount: float | None = None,
    stage: str | None = None,
) -> Literal["high", "medium", "low"]:
    if not issues:
        return "low"
    return max(issues, key=lambda i: SEVERITY_RANK[i.severity]).severity
