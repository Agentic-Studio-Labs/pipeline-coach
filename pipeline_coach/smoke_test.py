"""Smoke test: verify connectivity, schema, and dry-run the pipeline.

Steps:
  1. Load config (env + config/)
  2. Check Twenty connectivity (fetch companies)
  3. Verify schema fields (opportunities with all required fields, workspaceMembers)
  4. Dry-run pipeline (mock email_client, real Twenty, no LLM)
  5. Print results, exit non-zero on failure
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Minimal mock email client — records calls, never sends
# ---------------------------------------------------------------------------


class _MockEmailClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> str:
        self.calls.append({"to": to, "subject": subject})
        return f"mock-{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def _section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_config(config_dir: Path) -> tuple[Any, Any, Any] | None:
    """Load AppConfig, RulesConfig, EscalationConfig. Returns (app, rules, escalation) or None."""
    _section("1. Config")
    from pipeline_coach.config import load_app_config, load_escalation_config, load_rules_config

    try:
        app_config = load_app_config()
        _check("load_app_config", True, f"twenty_api_url={app_config.twenty_api_url}")
    except KeyError as exc:
        _check("load_app_config", False, f"missing env var: {exc}")
        return None

    rules_ok = True
    try:
        rules_config = load_rules_config(config_dir / "rules.yaml")
        _check("load_rules_config", True, f"excluded_stages={rules_config.excluded_stages}")
    except Exception as exc:
        _check("load_rules_config", False, str(exc))
        rules_ok = False
        rules_config = None  # type: ignore[assignment]

    escalation_ok = True
    try:
        escalation_config = load_escalation_config(config_dir / "escalation.yaml")
        _check(
            "load_escalation_config",
            True,
            f"default_manager={escalation_config.default_manager}",
        )
    except Exception as exc:
        _check("load_escalation_config", False, str(exc))
        escalation_ok = False
        escalation_config = None  # type: ignore[assignment]

    if not (rules_ok and escalation_ok):
        return None

    return app_config, rules_config, escalation_config


def check_twenty_connectivity(twenty_client: Any) -> bool:
    """Fetch companies — confirms API reachable and auth valid."""
    _section("2. Twenty connectivity")
    try:
        companies = twenty_client.fetch_all("companies", "id name")
        return _check("fetch companies", True, f"count={len(companies)}")
    except Exception as exc:
        return _check("fetch companies", False, str(exc))


def check_schema(twenty_client: Any) -> bool:
    """Confirm that opportunity and workspaceMember fields exist in the schema."""
    _section("3. Schema fields")
    all_ok = True

    # Opportunities — must include every field the normalizer reads
    try:
        opps = twenty_client.fetch_all(
            "opportunities",
            "id name amount { amountMicros currencyCode } stage closeDate "
            "createdAt updatedAt stageChangedAt companyId pointOfContactId ownerId",
        )
        all_ok &= _check(
            "opportunities (full field set)",
            True,
            f"count={len(opps)}",
        )
    except Exception as exc:
        all_ok &= _check("opportunities (full field set)", False, str(exc))

    # workspaceMembers
    try:
        members = twenty_client.fetch_all(
            "workspaceMembers",
            "id name { firstName lastName } userEmail",
        )
        all_ok &= _check("workspaceMembers", True, f"count={len(members)}")
    except Exception as exc:
        all_ok &= _check("workspaceMembers", False, str(exc))

    # tasks — must match fetch_tasks + normalizer (activity timestamps + targets)
    try:
        tasks = twenty_client.fetch_all(
            "tasks",
            "id createdAt updatedAt status completedAt "
            "taskTargets { edges { node { targetOpportunityId } } }",
        )
        all_ok &= _check("tasks (full field set)", True, f"count={len(tasks)}")
    except Exception as exc:
        all_ok &= _check("tasks (full field set)", False, str(exc))

    return all_ok


def check_dry_run(
    twenty_client: Any,
    rules_config: Any,
    escalation_config: Any,
) -> bool:
    """Run the full graph with a mock email client and no LLM."""
    _section("4. Dry-run pipeline")
    from pipeline_coach.workflow.graph import build_graph

    mock_email = _MockEmailClient()

    graph = build_graph(
        twenty_client=twenty_client,
        email_client=mock_email,
        rules_config=rules_config,
        escalation_config=escalation_config,
        use_llm=False,
        today=date.today(),
        excluded_stages=rules_config.excluded_stages,
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
        "run_id": "smoke",
        "emails_sent": 0,
        "emails_failed": 0,
        "errors": [],
    }

    try:
        result = graph.invoke(initial_state)
    except Exception as exc:
        return _check("graph.invoke", False, str(exc))

    errors = result.get("errors", [])
    graph_ok = _check(
        "graph.invoke",
        True,
        f"opportunities={len(result.get('opportunities', []))} "
        f"issues={len(result.get('validated_summaries', []))} "
        f"errors={len(errors)}",
    )

    if errors:
        print(f"    graph errors: {errors}")

    emails_ok = _check(
        "email_client mocked (no real sends)",
        True,
        f"would-send={len(mock_email.calls)}",
    )

    return graph_ok and emails_ok


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(config_dir: Path = Path("config")) -> int:
    print("Pipeline Coach — Smoke Test")
    print("=" * 40)

    configs = check_config(config_dir)
    if configs is None:
        print("\nSmoke test FAILED (config errors — see above)")
        return 1

    app_config, rules_config, escalation_config = configs

    from pipeline_coach.ingestion.twenty_client import TwentyClient

    twenty_client = TwentyClient(
        base_url=app_config.twenty_api_url,
        api_key=app_config.twenty_api_key,
    )

    try:
        connectivity_ok = check_twenty_connectivity(twenty_client)
        if not connectivity_ok:
            print("\nSmoke test FAILED (cannot reach Twenty — see above)")
            return 1

        schema_ok = check_schema(twenty_client)
        dry_run_ok = check_dry_run(twenty_client, rules_config, escalation_config)
    finally:
        twenty_client.close()

    print()
    all_ok = connectivity_ok and schema_ok and dry_run_ok
    if all_ok:
        print("Smoke test PASSED")
        return 0
    else:
        print("Smoke test FAILED — see details above")
        return 1


if __name__ == "__main__":
    config_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config")
    sys.exit(main(config_dir))
