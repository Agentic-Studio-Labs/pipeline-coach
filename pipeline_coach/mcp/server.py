from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from pipeline_coach.config import load_app_config, load_rules_config
from pipeline_coach.ingestion.twenty_client import TwentyClient
from pipeline_coach.mcp.helpers import get_crm_url
from pipeline_coach.mcp.tools import (
    handle_analyze_pipeline,
    handle_get_audit_history,
    handle_get_company_overview,
    handle_get_deal_issues,
    handle_get_deal_overview,
    handle_get_rules_config,
    handle_get_run_details,
    handle_list_stale_deals,
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

# Lazy-initialized state
_twenty_client: TwentyClient | None = None
_app_config = None
_rules_config = None
_crm_url: str = ""
_config_dir = Path("config")


def _ensure_initialized() -> None:
    global _twenty_client, _app_config, _rules_config, _crm_url
    if _twenty_client is not None:
        return
    _app_config = load_app_config()
    _rules_config = load_rules_config(_config_dir / "rules.yaml")
    _twenty_client = TwentyClient(
        base_url=_app_config.twenty_api_url,
        api_key=_app_config.twenty_api_key,
    )
    _crm_url = get_crm_url(_app_config)
    if _app_config.llm_api_key:
        import dspy
        from dspy.adapters import ChatAdapter

        lm = dspy.LM(
            _app_config.llm_model, api_key=_app_config.llm_api_key, temperature=0.7, max_tokens=200
        )
        dspy.configure(lm=lm, adapter=ChatAdapter())


mcp = FastMCP(
    "pipeline-coach",
    instructions="Pipeline Coach: query CRM deal health, run hygiene analysis, and inspect audit history.",
)


# ---------------------------------------------------------------------------
# Tools — CRM-backed (require TwentyClient)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def analyze_pipeline(
    use_llm: Annotated[
        bool, Field(description="Whether to call the LLM for suggested actions")
    ] = False,
) -> dict[str, Any]:
    """Run a full pipeline hygiene analysis across all active opportunities."""
    _ensure_initialized()
    return handle_analyze_pipeline(
        use_llm=use_llm,
        twenty_client=_twenty_client,
        rules_config=_rules_config,
        crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_deal_overview(
    query: Annotated[str, Field(description="Deal name, substring, or UUID to look up")],
    use_llm: Annotated[
        bool, Field(description="Whether to call the LLM for suggested actions")
    ] = False,
) -> dict[str, Any]:
    """Get a full overview of a single deal including issues and suggested action."""
    _ensure_initialized()
    return handle_get_deal_overview(
        query=query,
        use_llm=use_llm,
        twenty_client=_twenty_client,
        rules_config=_rules_config,
        crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_company_overview(
    company_name: Annotated[str, Field(description="Company name or substring to look up")],
) -> dict[str, Any]:
    """Get all deals associated with a company, with hygiene issues for each."""
    _ensure_initialized()
    return handle_get_company_overview(
        company_name=company_name,
        twenty_client=_twenty_client,
        rules_config=_rules_config,
        crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_deal_issues(
    query: Annotated[str, Field(description="Deal name, substring, or UUID to look up")],
) -> dict[str, Any]:
    """List hygiene issues for a specific deal without generating suggested actions."""
    _ensure_initialized()
    return handle_get_deal_issues(
        query=query,
        twenty_client=_twenty_client,
        rules_config=_rules_config,
        crm_url=_crm_url,
    )


@mcp.tool(annotations=_READ_ONLY)
def list_stale_deals(
    min_days: Annotated[
        int | None, Field(description="Only include deals stale for at least this many days")
    ] = None,
) -> dict[str, Any]:
    """List all deals that have been stale in their current stage beyond the configured threshold."""
    _ensure_initialized()
    return handle_list_stale_deals(
        min_days=min_days,
        twenty_client=_twenty_client,
        rules_config=_rules_config,
        crm_url=_crm_url,
    )


# ---------------------------------------------------------------------------
# Tools — audit / config (no TwentyClient needed)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def get_audit_history(
    limit: Annotated[int, Field(description="Maximum number of recent runs to return")] = 10,
) -> dict[str, Any]:
    """Return the most recent pipeline hygiene audit runs from the audit log."""
    return handle_get_audit_history(limit=limit)


@mcp.tool(annotations=_READ_ONLY)
def get_run_details(
    run_id: Annotated[
        str, Field(description="Run ID (e.g. mcp-abc12345) to retrieve details for")
    ],
) -> dict[str, Any]:
    """Return the full issue list for a specific audit run by run ID."""
    return handle_get_run_details(run_id=run_id)


@mcp.tool(annotations=_READ_ONLY)
def get_rules_config() -> dict[str, Any]:
    """Return the current hygiene rules configuration."""
    return handle_get_rules_config(config_dir=_config_dir)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("pipelinecoach://config/rules")
def resource_rules_config() -> str:
    """Current hygiene rules YAML."""
    return (_config_dir / "rules.yaml").read_text()


@mcp.resource("pipelinecoach://config/escalation")
def resource_escalation_config() -> str:
    """Current escalation rules YAML."""
    return (_config_dir / "escalation.yaml").read_text()


@mcp.resource("pipelinecoach://audit/latest")
def resource_audit_latest() -> str:
    """Latest audit run record as JSON, or an empty object if no runs exist."""
    from pipeline_coach.mcp.helpers import read_audit_runs

    runs = read_audit_runs(limit=1)
    if not runs:
        return json.dumps({})
    return json.dumps(runs[-1], indent=2)
