from collections import defaultdict
from dataclasses import dataclass, field

from pipeline_coach.config import EscalationConfig
from pipeline_coach.models import IssueSummary


@dataclass
class RoutingResult:
    ae_briefs: dict[str, list[IssueSummary]] = field(default_factory=dict)
    escalations: dict[str, list[IssueSummary]] = field(default_factory=dict)


def _is_critical(summary: IssueSummary, threshold: float) -> bool:
    return (
        summary.priority == "high"
        and summary.context.amount is not None
        and summary.context.amount >= threshold
    )


def route_summaries(
    summaries: list[IssueSummary], escalation_config: EscalationConfig
) -> RoutingResult:
    ae_groups: dict[str, list[IssueSummary]] = defaultdict(list)
    escalation_groups: dict[str, list[IssueSummary]] = defaultdict(list)
    for s in summaries:
        ae_groups[s.owner_email].append(s)
        if _is_critical(s, escalation_config.critical_amount_threshold):
            manager = escalation_config.get_manager(s.owner_email)
            escalation_groups[manager].append(s)
    return RoutingResult(ae_briefs=dict(ae_groups), escalations=dict(escalation_groups))
