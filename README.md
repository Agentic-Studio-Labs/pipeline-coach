# Pipeline Coach

A daily pipeline hygiene coach for [Twenty CRM](https://twenty.com). Scans open opportunities for staleness, missing data, and overdue close dates; generates suggested actions; and emails each AE a concise brief every morning.

**License:** Apache 2.0

---

## Quickstart

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set TWENTY_API_KEY, RESEND_API_KEY, EMAIL_FROM

# 2. Start Twenty CRM + Pipeline Coach
docker compose up

# 3. Seed Twenty with sample data (optional)
docker compose run --rm pipeline-coach python scripts/seed_twenty.py

# 4. Verify connectivity (smoke test)
docker compose run --rm pipeline-coach-smoke

# 5. Run the pipeline manually
docker compose run --rm pipeline-coach python -m pipeline_coach --once
```

The scheduler service (`pipeline-coach`) runs automatically at `RUN_AT_HOUR` (default 08:00 local time) each day.

---

## How It Works

The pipeline runs as a LangGraph state machine with six stages:

1. **Ingest** — Five parallel nodes fetch companies, people, opportunities, tasks, and workspace members from the Twenty GraphQL API.
2. **Normalize** — Raw records are joined and enriched into `OpportunityContext` objects: owner name/email, company name, contact email, open task count, days stale.
3. **Evaluate rules** — Each opportunity is checked against configurable rules: stale in stage, no recent activity, close date past, close date soon with no activity, missing amount, missing close date, missing decision maker.
4. **Generate actions** — A fallback heuristic (or optional LLM via DSPy) produces a one-sentence suggested action for each flagged opportunity.
5. **Quality gate** — Validates that each suggested action is non-empty and addresses at least one flagged issue. LLM-generated actions retry up to 2 times before falling back to heuristic.
6. **Route and deliver** — Opportunities are bucketed by severity and escalation config. Each AE receives a prioritized brief; managers are CC'd when configured thresholds are exceeded. Emails are sent via Resend.

---

## Configuration

All configuration lives in `config/` (YAML files) and `.env` (secrets and runtime settings).

### `config/rules.yaml`

Controls which hygiene rules are active and their thresholds:

```yaml
excluded_stages:
  - CLOSED_WON
  - CLOSED_LOST

rules:
  stale_in_stage:
    enabled: true
    default_days: 14
    by_stage:
      MEETING_SCHEDULED: 7
      PROPOSAL_SENT: 10
    severity: high

  no_recent_activity:
    enabled: true
    days: 7
    severity: medium

  close_date_past:
    enabled: true
    severity: high

  close_date_soon_no_activity:
    enabled: true
    close_date_soon_days: 7
    no_activity_days: 3
    severity: high

  missing_amount:
    enabled: true
    severity: medium

  missing_close_date:
    enabled: true
    severity: medium

  missing_decision_maker:
    enabled: true
    by_stage:
      PROPOSAL_SENT: true
      NEGOTIATION: true
    severity: low
```

### `config/escalation.yaml`

Controls when issues are escalated to a manager:

```yaml
default_manager: manager@example.com
critical_amount_threshold: 50000.0
overrides:
  ae@example.com: their-manager@example.com
```

### `.env`

| Variable | Required | Description |
|---|---|---|
| `TWENTY_API_URL` | Yes | Twenty CRM base URL (e.g. `http://twenty:3000`) |
| `TWENTY_API_KEY` | Yes | Twenty API key |
| `RESEND_API_KEY` | Yes | Resend API key for sending emails |
| `EMAIL_FROM` | Yes | Sender address (e.g. `coach@yourcompany.com`) |
| `LLM_API_KEY` | No | Enables LLM-generated actions via DSPy |
| `LLM_MODEL` | No | DSPy model string (default: `openai/gpt-4o-mini`) |
| `RUN_AT_HOUR` | No | Hour (0–23) to run daily (default: `8`) |
| `AUDIT_REDACT_PII` | No | Redact emails/names in audit log (default: `false`) |
| `AUDIT_LOG_RETENTION_DAYS` | No | Days to retain audit records (default: `30`) |

---

## Running

| Command | Description |
|---|---|
| `python -m pipeline_coach` | Start the scheduler (runs daily at `RUN_AT_HOUR`) |
| `python -m pipeline_coach --once` | Run the pipeline once and exit |
| `python -m pipeline_coach.show_recent --owner ae@example.com` | Show last run results for an AE |
| `python -m pipeline_coach.smoke_test` | Connectivity, schema, and dry-run check |
| `python scripts/seed_twenty.py` | Seed Twenty with sample companies, contacts, and opportunities |

---

## Testing

### Unit tests

```bash
pip install -e ".[dev]"
pytest
```

Tests cover rule evaluation, priority scoring, normalizer, brief rendering, escalation routing, and quality gate. The LLM and email clients are mocked.

### Smoke test

The smoke test (`pipeline_coach/smoke_test.py`) verifies:

1. Config loads correctly from env and `config/`
2. Twenty CRM is reachable and the API key is valid
3. The required GraphQL schema fields exist (opportunities with all fields, workspaceMembers)
4. The full pipeline graph completes a dry run against real data with a mock email client

Run it before deploying or after a Twenty upgrade:

```bash
python -m pipeline_coach.smoke_test
# or via docker compose:
docker compose run --rm pipeline-coach-smoke
```

Exit code 0 = all checks passed. Non-zero = failure details printed to stdout.

---

## Architecture

**Monolith, single process.** Pipeline Coach is a single Python process: no worker queues, no databases of its own, no external state beyond the Twenty API and the local audit log (`data/audit_log.jsonl`).

**Read-only against Twenty.** The agent never writes back to Twenty CRM. All mutations (task creation, note updates) are left as future work.

**Agent identity.** When `LLM_API_KEY` is set, DSPy calls the configured LLM to generate one-sentence suggested actions. Without a key, a deterministic heuristic generates fallback actions. The quality gate runs either way.

**Audit log.** Every run appends JSONL records to `data/audit_log.jsonl`: one `run` record and one `issue` record per flagged opportunity. PII (email addresses, names) can be redacted with `AUDIT_REDACT_PII=true`.

**Slack (future).** Delivery currently supports email only. A Slack delivery channel is planned for v2.

---

## Tech Stack

| Component | Library |
|---|---|
| Workflow graph | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM integration | [DSPy](https://github.com/stanfordnlp/dspy) |
| CRM client | [Twenty GraphQL API](https://twenty.com) via [httpx](https://www.python-httpx.org/) |
| Email delivery | [Resend](https://resend.com) |
| Data models | [Pydantic v2](https://docs.pydantic.dev/) |
| Scheduling | [APScheduler](https://apscheduler.readthedocs.io/) |
| Structured logging | [structlog](https://www.structlog.org/) |
| Config parsing | PyYAML |
| Testing | pytest + pytest-mock |
| Linting/formatting | ruff |
