# Pipeline Coach

A daily pipeline hygiene coach for [Twenty CRM](https://twenty.com). Scans open opportunities for staleness, missing data, and overdue close dates, generates suggested next-best-actions (via LLM or deterministic templates), and emails each AE a prioritized brief every morning. Critical deals are escalated to managers.

**License:** Apache 2.0

---

## Quickstart

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set TWENTY_API_KEY (get from Twenty Settings > APIs & Webhooks)
# Set RESEND_API_KEY and EMAIL_FROM for email delivery
# LLM_API_KEY is optional — leave commented out for deterministic actions

# 2. Start Twenty CRM
docker compose up -d twenty-db twenty-redis twenty twenty-worker

# 3. Wait for Twenty to become healthy (~60-90 seconds for first boot)
docker compose ps  # wait until twenty shows "healthy"

# 4. Open Twenty and create your workspace
open http://localhost:3000
# Sign up, then go to Settings > APIs & Webhooks > Create API Key
# Copy the key into .env as TWENTY_API_KEY

# 5. Seed sample data (creates companies, contacts, opportunities, tasks)
.venv/bin/python scripts/seed_twenty.py
# Use --nuke to wipe ALL existing data first
# Use --clean to remove only previously seeded data

# 6. Run the pipeline once
.venv/bin/python -m pipeline_coach --once

# 7. View audit dashboard
.venv/bin/python -m pipeline_coach.dashboard
# Open http://localhost:8080
```

### Docker-only quickstart

```bash
docker compose up -d                                          # start everything
docker compose run --rm pipeline-coach-smoke                  # verify connectivity
docker compose run --rm pipeline-coach python -m pipeline_coach --once  # run pipeline
```

Note: when running inside Docker, the Twenty URL is `http://twenty:3000` (set in `.env.example`). When running locally outside Docker, use `http://localhost:3000`.

---

## How It Works

Pipeline Coach runs as a [LangGraph](https://github.com/langchain-ai/langgraph) state machine:

1. **Parallel fetch** — Five nodes concurrently fetch companies, people, opportunities, tasks, and workspace members from Twenty's GraphQL API.
2. **Normalize** — Raw records are joined into `OpportunityContext` objects: owner name/email (from workspace members), company name, last activity date (from linked tasks), days in stage (from `stageChangedAt` custom field).
3. **Rule evaluation** — Each opportunity is checked against 7 configurable hygiene rules. Terminal stages (e.g., `CUSTOMER`) are filtered out.
4. **Action generation** — [DSPy](https://dspy.ai) generates a context-aware suggested action per deal via LLM. Without an LLM key, deterministic templates provide fallback actions.
5. **Quality gate** — Validates each suggested action is non-empty, contains an action verb, and isn't just restating the issue. LLM actions retry up to 2x before falling back to templates.
6. **Route and deliver** — Deals are grouped by AE. High-priority deals above the amount threshold are escalated to managers. Emails are sent via [Resend](https://resend.com) with deep links to each opportunity in Twenty.

---

## Configuration

### `config/rules.yaml`

Controls which hygiene rules fire and their thresholds. Stage names must match your Twenty CRM stages (default: `NEW`, `SCREENING`, `MEETING`, `PROPOSAL`, `CUSTOMER`).

```yaml
excluded_stages:
  - CUSTOMER          # terminal stage — skip these opportunities

rules:
  stale_in_stage:
    enabled: true
    default_days: 14  # days before flagging as stale
    by_stage:
      SCREENING: 21   # more patience for early-stage
      PROPOSAL: 7     # less patience for late-stage
    severity: medium

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
    no_activity_days: 7
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
      PROPOSAL: true  # only flag in these stages
    severity: low
```

### `config/escalation.yaml`

Controls when and where critical deals are escalated:

```yaml
escalation:
  default_manager: vp-sales@yourcompany.com
  overrides:
    ae1@yourcompany.com: manager-a@yourcompany.com
    ae2@yourcompany.com: manager-b@yourcompany.com
  critical_amount_threshold: 50000   # high priority + amount >= this triggers escalation
```

### `.env`


| Variable                   | Required | Default              | Description                                                                                        |
| -------------------------- | -------- | -------------------- | -------------------------------------------------------------------------------------------------- |
| `TWENTY_API_URL`           | Yes      | —                    | Twenty CRM base URL (`http://localhost:3000` locally, `http://twenty:3000` in Docker)              |
| `TWENTY_API_KEY`           | Yes      | —                    | Twenty API key (Settings > APIs & Webhooks)                                                        |
| `RESEND_API_KEY`           | Yes      | —                    | [Resend](https://resend.com) API key                                                               |
| `EMAIL_FROM`               | Yes      | —                    | Sender address (must be verified domain in Resend)                                                 |
| `LLM_API_KEY`              | No       | —                    | Enables LLM-generated actions via DSPy. Supports any [LiteLLM](https://docs.litellm.ai/) provider. |
| `LLM_MODEL`                | No       | `openai/gpt-4o-mini` | Model string in `provider/model` format                                                            |
| `RUN_AT_HOUR`              | No       | `8`                  | Hour (0-23) for the daily scheduler                                                                |
| `AUDIT_REDACT_PII`         | No       | `false`              | Redact owner emails/names in audit log                                                             |
| `AUDIT_LOG_RETENTION_DAYS` | No       | `30`                 | Days to retain audit records                                                                       |


For Docker Compose, `TWENTY_APP_SECRET` is also needed (auto-generated with a default in docker-compose.yml).

---

## Running


| Command                                                  | Description                                                             |
| -------------------------------------------------------- | ----------------------------------------------------------------------- |
| `python -m pipeline_coach --once`                        | Run the pipeline once and exit                                          |
| `python -m pipeline_coach`                               | Start the daily scheduler (runs at `RUN_AT_HOUR`)                       |
| `python -m pipeline_coach.dashboard`                     | Audit trail dashboard at [http://localhost:8080](http://localhost:8080) |
| `python -m pipeline_coach.show_recent --owner ae@co.com` | Show last run results for an AE                                         |
| `python -m pipeline_coach.smoke_test`                    | Connectivity + schema + dry-run check                                   |
| `python scripts/seed_twenty.py`                          | Seed Twenty with sample data                                            |
| `python scripts/seed_twenty.py --nuke`                   | Wipe ALL CRM data, then seed fresh                                      |
| `python scripts/seed_twenty.py --clean`                  | Remove previously seeded data only                                      |


### Docker Compose services


| Service                    | Port | Description              |
| -------------------------- | ---- | ------------------------ |
| `twenty`                   | 3000 | Twenty CRM               |
| `twenty-db`                | —    | PostgreSQL 16            |
| `twenty-redis`             | —    | Redis (queues/cache)     |
| `twenty-worker`            | —    | Twenty background worker |
| `pipeline-coach`           | —    | Daily scheduler          |
| `pipeline-coach-dashboard` | 8080 | Audit trail web UI       |
| `pipeline-coach-smoke`     | —    | One-shot smoke test      |


---

## Seed Script

The seed script (`scripts/seed_twenty.py`) creates:

- 5 companies (Acme Corp, Northwind, GlobalSoft, Brightwave, NimbusHQ)
- 10 contacts with company associations
- 15 opportunities across stages with varied hygiene issues (missing amounts, past close dates, stale deals)
- 8 tasks linked to opportunities via `taskTargets`
- A `stageChangedAt` custom field on the Opportunity object (for accurate days-in-stage tracking)

The script also auto-detects the first workspace member and assigns them as the owner of all seeded opportunities.

---

## Testing

```bash
pip install -e ".[dev]"
pytest
```

**139 unit tests** covering rule evaluation, priority scoring, normalizer (GraphQL response mapping), brief rendering, escalation routing, quality gate, audit logging, and workflow graph nodes. External services (Twenty, Resend, LLM) are mocked.

The **smoke test** verifies real connectivity:

```bash
python -m pipeline_coach.smoke_test
# or: docker compose run --rm pipeline-coach-smoke
```

---

## Architecture

**Single process, read-only.** Pipeline Coach never writes to Twenty CRM. All output is delivered as email suggestions for humans to act on.

**LangGraph orchestration** with three patterns that justify the framework: parallel fan-out (5 concurrent GraphQL fetches), quality gate retry loop (generate action -> validate -> retry or fallback), and conditional escalation routing (critical deals branch to manager path).

Business-friendly one-screen view (image):

Pipeline Coach executive architecture

Direct PNG link: [pipeline-coach-architecture-exec.png](docs/diagrams/pipeline-coach-architecture-exec.png)

### Architecture ownership map

High-level flow (the table below maps each block to concrete files):

- Trigger -> LangGraph workflow
- Workflow -> Fetch Twenty data -> Normalize context -> Evaluate rules and priority -> Generate suggested action -> Quality gate and retry -> Route and render briefs -> Send emails
- Workflow -> Write audit log
- Generate suggested action -> LLM provider path

### Responsibility table


| Concern                    | Primary owner           | Key files                                                               | Notes                                                     |
| -------------------------- | ----------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------- |
| Workflow orchestration     | LangGraph               | `pipeline_coach/workflow/graph.py`                                      | Controls fan-out/fan-in, retry loop, and routing          |
| Action generation          | DSPy                    | `pipeline_coach/coach/actions.py`                                       | Produces suggested action text using LLM when enabled     |
| LLM transport/provider     | LiteLLM + provider API  | DSPy runtime path                                                       | Handles auth, model routing, and provider response format |
| CRM ingestion              | Twenty GraphQL + httpx  | `pipeline_coach/ingestion/twenty_client.py`                             | Read-only pulls from Twenty                               |
| Business logic             | Rule engine + scoring   | `pipeline_coach/hygiene/rules.py`, `pipeline_coach/hygiene/priority.py` | Determines which deals are flagged and severity           |
| Message routing/formatting | Router + brief renderer | `pipeline_coach/delivery/router.py`, `pipeline_coach/coach/brief.py`    | Groups by AE/manager and renders plain-text messages      |
| Delivery                   | Resend client           | `pipeline_coach/delivery/email_client.py`                               | Sends AE and escalation emails                            |
| Auditability               | Observability logger    | `pipeline_coach/observability/logger.py`                                | Writes run and issue records to JSONL                     |


### Error ownership example

- If you see a DSPy/adapter warning followed by deterministic fallback, the workflow itself is still running.
- In that case, the failure usually lives in the LLM transport/provider layer (credentials, model string, provider capabilities), not in LangGraph routing logic.

**Audit trail.** Every run appends JSONL records to `data/audit_log.jsonl` — one run summary and one record per flagged opportunity. View via the dashboard at port 8080 or the CLI (`show_recent`). PII redaction available via `AUDIT_REDACT_PII=true`.

**Custom CRM field.** The seed script creates a `stageChangedAt` DateTime field on the Opportunity object in Twenty. This enables accurate "days in stage" tracking (Twenty's built-in `updatedAt` resets on any field edit, not just stage changes).

---

## Why Agentic Patterns

### What it delivers in v1

**Reliable action output.** Suggested actions run through a quality gate (non-empty, action-oriented, not just restating the issue). If LLM output fails quality checks, the workflow retries per opportunity and then falls back to deterministic templates.

**Explicit, testable orchestration.** LangGraph defines the pipeline as named stages with clear transitions: fetch -> normalize -> evaluate -> generate -> validate -> route -> deliver. This makes flow control and failure handling easier to reason about than ad hoc branching.

**Targeted escalation.** The routing step separates normal AE guidance from manager escalation based on priority and amount thresholds, so high-risk deals are highlighted without spamming managers on every issue.

### What it does not claim

- It is not an autonomous research agent. It does not independently choose tools or goals at runtime.
- It is not real-time in v1; it is a scheduled batch workflow.
- It is not positioned as infinite-scale architecture in v1; it is designed for practical daily CRM hygiene runs.

### Scale posture (today vs next)

**Today:** full-scan, paginated ingestion; in-memory normalization and rule evaluation; LLM calls only for flagged opportunities with bounded retries.

**Next for larger datasets:** move to incremental fetch windows, partition processing into chunks, and apply selective LLM generation (for top-priority subsets first) to control latency and cost.

### Why this still helps as the product grows

| Growth need | Pattern already in place | Practical next step |
| --- | --- | --- |
| Human feedback loop | Stateful graph stages | Add reply/webhook input to update next-run behavior |
| Higher data volume | Fan-out/fan-in boundaries | Incremental sync + chunked execution + queue workers |
| Lower LLM cost | Quality gate + deterministic fallback | Prioritize LLM on highest-impact opportunities only |
| New delivery channels | Routing node abstraction | Add Slack or CRM-task branch without rewriting core rules |
| Multi-CRM support | Normalizer boundary | Add connector-specific mappers into shared `OpportunityContext` |

### Foundation first

Core value does not depend on LLM novelty:

- Deterministic YAML-driven rule engine
- Structured data models (`OpportunityContext`, `Issue`, `IssueSummary`)
- Stable normalization layer for CRM schema drift
- Per-run audit trail for traceability
- Quality gate and bounded retry behavior for safer automation

### TODOs (near-term)

- [x] Add one-sentence "Why now" rationale per suggested action (implemented in v1)
- [ ] Add per-AE action dedupe/synthesis to reduce repetitive guidance
- [ ] Add checkpoint/resume for interrupted runs
- [ ] Add selective LLM generation for highest-impact opportunities first

---

## Tech Stack


| Component                | Library                                                                                 |
| ------------------------ | --------------------------------------------------------------------------------------- |
| Workflow                 | [LangGraph](https://github.com/langchain-ai/langgraph)                                  |
| LLM                      | [DSPy 3.x](https://github.com/stanfordnlp/dspy) via [LiteLLM](https://docs.litellm.ai/) |
| CRM                      | [Twenty GraphQL API](https://twenty.com) via [httpx](https://www.python-httpx.org/)     |
| Email                    | [Resend](https://resend.com)                                                            |
| Data models & validation | [Pydantic v2](https://docs.pydantic.dev/)                                               |
| Scheduling               | [APScheduler](https://apscheduler.readthedocs.io/)                                      |
| Logging                  | [structlog](https://www.structlog.org/)                                                 |
| Testing                  | pytest + pytest-mock                                                                    |
| Linting                  | ruff                                                                                    |


