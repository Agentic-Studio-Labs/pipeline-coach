from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog

from pipeline_coach.models import IssueSummary


def setup_logging() -> None:
    log_level_raw = os.environ.get("LOG_LEVEL", "INFO")
    try:
        log_level = int(log_level_raw)
    except ValueError:
        log_level = getattr(logging, log_level_raw.upper(), logging.INFO)

    use_json = os.environ.get("LOG_FORMAT", "").lower() == "json"

    renderer: structlog.types.Processor
    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def write_audit_record(
    *,
    run_id: str,
    summaries: list[IssueSummary],
    emails_sent: int,
    emails_failed: int,
    errors: list[str] | None = None,
    redact_pii: bool = False,
    audit_dir: Path | None = None,
) -> None:
    if audit_dir is None:
        audit_dir = Path("data")

    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit_log.jsonl"

    now = datetime.now(UTC).isoformat()

    run_record: dict = {
        "type": "run",
        "run_id": run_id,
        "timestamp": now,
        "opportunities_with_issues": len(summaries),
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
        "errors": errors or [],
    }

    issue_records: list[dict] = []
    for summary in summaries:
        owner_email = "[REDACTED]" if redact_pii else summary.owner_email
        issue_records.append(
            {
                "type": "issue",
                "run_id": run_id,
                "timestamp": now,
                "opportunity_id": summary.opportunity_id,
                "opportunity_name": summary.opportunity_name,
                "owner_email": owner_email,
                "priority": summary.priority,
                "rule_ids": [issue.rule_id for issue in summary.issues],
                "suggested_action": summary.suggested_action,
                "action_rationale": summary.action_rationale,
            }
        )

    log = structlog.get_logger()
    try:
        with audit_path.open("a") as fh:
            fh.write(json.dumps(run_record) + "\n")
            for record in issue_records:
                fh.write(json.dumps(record) + "\n")
    except IOError as exc:
        log.warning("audit_write_failed", path=str(audit_path), error=str(exc))
