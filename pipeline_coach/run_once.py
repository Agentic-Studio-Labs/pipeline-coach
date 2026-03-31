import uuid
from datetime import date
from pathlib import Path

import structlog

from pipeline_coach.config import (
    AppConfig,
    load_app_config,
    load_escalation_config,
    load_rules_config,
)
from pipeline_coach.delivery.email_client import ResendClient
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.observability.logger import setup_logging, write_audit_record
from pipeline_coach.workflow.graph import build_graph

logger = structlog.get_logger()


def run_pipeline_once(
    *, config_dir: Path = Path("config"), app_config: AppConfig | None = None
) -> dict:
    setup_logging()
    app_config = app_config or load_app_config()
    rules_config = load_rules_config(config_dir / "rules.yaml")
    escalation_config = load_escalation_config(config_dir / "escalation.yaml")

    twenty_client = TwentyClient(
        base_url=app_config.twenty_api_url, api_key=app_config.twenty_api_key
    )
    email_client = ResendClient(
        api_key=app_config.resend_api_key, from_email=app_config.email_from
    )

    run_id = str(uuid.uuid4())[:8]
    today = date.today()
    excluded_stages = rules_config.excluded_stages

    logger.info("pipeline_start", run_id=run_id, today=str(today))

    graph = build_graph(
        twenty_client=twenty_client,
        email_client=email_client,
        rules_config=rules_config,
        escalation_config=escalation_config,
        use_llm=app_config.llm_api_key is not None,
        today=today,
        excluded_stages=excluded_stages,
        crm_url=app_config.twenty_api_url,
    )

    initial_state = {
        "companies": [],
        "people": [],
        "opportunities": [],
        "tasks": [],
        "workspace_members": [],
        "contexts": [],
        "validated_summaries": [],
        "pending_summaries": [],
        "ae_briefs": {},
        "escalation_briefs": {},
        "action_retry_count_by_opp": {},
        "run_id": run_id,
        "emails_sent": 0,
        "emails_failed": 0,
        "errors": [],
    }

    result = graph.invoke(initial_state)

    write_audit_record(
        run_id=run_id,
        summaries=result["validated_summaries"],
        emails_sent=result["emails_sent"],
        emails_failed=result["emails_failed"],
        redact_pii=app_config.audit_redact_pii,
    )

    logger.info(
        "pipeline_complete",
        run_id=run_id,
        issues=len(result["validated_summaries"]),
        emails_sent=result["emails_sent"],
        emails_failed=result["emails_failed"],
        errors=result["errors"],
    )

    twenty_client.close()
    return result
