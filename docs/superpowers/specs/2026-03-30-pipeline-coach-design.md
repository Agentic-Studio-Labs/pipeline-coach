# Pipeline Coach — Design Spec

## Overview

A daily pipeline hygiene coach that connects to a self-hosted Twenty CRM, identifies at-risk and poorly maintained deals, and emails each AE a prioritized list of actions. Critical deals are escalated to managers.

**License:** Apache 2.0

---

## Validated Against

This v1 demo spec is validated for a local end-to-end flow (seed -> ingest -> score -> brief -> deliver) against:

- Twenty CRM (self-hosted Docker image `twentyhq/twenty:latest`, validated snapshot on 2026-03-30)
- Pipeline Coach run modes: one-off (`python -m pipeline_coach --once`) and scheduled (`python -m pipeline_coach`)
- Resend API delivery path for AE briefs and manager escalations

### Confirmed GraphQL fields (v1 normalizer contract)

- **Companies:** `id`, `name`
- **People:** `id`, `name`, `email`, `company { id }`
- **Opportunities:** `id`, `name`, `amount`, `stage`, `closeDate`, `createdAt`, `updatedAt`, `pointOfContact { id }`, `company { id }`
- **Activities/Tasks:** `id`, `type`, `createdAt`, `assignee { id }`, `opportunity { id }`

The normalizer isolates field-level mapping so schema drift can be handled in one place if Twenty changes.

### Required environment variables

For this repo's local demo path:

- **Pipeline Coach:** `TWENTY_API_URL`, `TWENTY_API_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`, `RUN_AT_HOUR`
- **Twenty container:** `DATABASE_URL`
- **Common Twenty self-hosted requirement:** `SERVER_URL`, `FRONT_BASE_URL` (set explicitly in local/prod deployments)

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Orchestration | LangGraph | Workflow uses parallel fan-out, conditional branching, and retry loops — patterns LangGraph handles well |
| LLM integration | DSPy | Typed signatures set up for future prompt optimization; v1 uses `dspy.Predict` without an optimizer |
| CRM API | Twenty GraphQL | Primary API, fewer round trips, richer queries than REST |
| Rule config | YAML files | RevOps can tune per-stage thresholds without touching code |
| Escalation config | YAML with default + overrides | Explicit AE-to-manager mapping, no dependency on CRM hierarchy data |
| Email delivery | Resend API | No SMTP; simple HTTP API |
| Testing (v1) | Unit tests + compose smoke test | Mock externals in unit tests; full integration suite and contracts are future work |
| Project structure | Monolith package | Single `pipeline_coach/` package; microservices noted as future option |
| Slack | Future TODO | Design message rendering to be reusable for Slack DMs later |

---

## Architecture

### LangGraph Workflow

```
start
  → [fetch_companies | fetch_people | fetch_opps | fetch_activities]  (parallel fan-out)
  → join_data                          (merge into OpportunityContext[])
  → compute_issues                     (deterministic rules from YAML)
  → generate_actions                   (DSPy suggested actions)
  → validate_actions                   (quality gate)
       ├─ pass → continue
       └─ fail → loop back to generate_actions (max 2 retries, then deterministic fallback)
  → route_by_severity
       ├─ critical → generate_manager_escalation + generate_ae_brief → send_emails
       └─ normal   → generate_ae_brief → send_emails
  → end
```

**Why this workflow justifies LangGraph:**
- **Parallel fan-out:** 4 concurrent GraphQL fetches, joined before processing
- **Retry loop (cycle):** LLM quality gate can reject and regenerate suggested actions
- **Conditional routing:** Critical deals branch to an escalation path alongside the normal AE brief

### Components

```
pipeline-coach/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── LICENSE                    # Apache 2.0
├── README.md
├── pyproject.toml
├── config/
│   ├── rules.yaml             # Hygiene rules + thresholds (per-stage)
│   └── escalation.yaml        # AE→manager mapping
├── pipeline_coach/
│   ├── __init__.py
│   ├── __main__.py            # Entry: python -m pipeline_coach
│   ├── run_once.py            # Single pipeline run (manual trigger)
│   ├── scheduler.py           # APScheduler daily loop
│   ├── smoke_test.py          # Compose smoke test entrypoint
│   ├── show_recent.py         # CLI: inspect recent owner brief/audit output
│   ├── config.py              # Load env vars + YAML configs
│   ├── models.py              # Pydantic: OpportunityContext, IssueSummary, Brief
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── twenty_client.py   # GraphQL client for Twenty CRM
│   │   └── normalizer.py      # Raw GQL responses → OpportunityContext
│   ├── hygiene/
│   │   ├── __init__.py
│   │   ├── rules.py           # Rule engine: loads YAML, evaluates opps
│   │   └── priority.py        # Priority scoring (amount x stage x severity)
│   ├── coach/
│   │   ├── __init__.py
│   │   ├── actions.py         # DSPy module: generate suggested actions
│   │   ├── quality_gate.py    # Validate LLM output, decide retry vs fallback
│   │   └── brief.py           # Render briefs (text format, Slack-ready later)
│   ├── delivery/
│   │   ├── __init__.py
│   │   ├── email_client.py    # Resend API client
│   │   └── router.py          # Route briefs: AE email + manager escalation
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── graph.py           # LangGraph state machine definition
│   │   └── state.py           # TypedDict for graph state
│   └── observability/
│       ├── __init__.py
│       └── logger.py          # Structured logging, run audit records
├── scripts/
│   └── seed_twenty.py         # Seed sample data into Twenty
├── tests/
│   ├── conftest.py
│   ├── test_rules.py
│   ├── test_priority.py
│   ├── test_brief.py
│   ├── test_quality_gate.py
│   └── test_normalizer.py
└── docs/
```

---

## Data Models

### OpportunityContext (Pydantic)

```python
class OpportunityContext(BaseModel):
    id: str
    name: str
    amount: float | None
    stage: str
    owner_email: str
    owner_name: str | None
    company_name: str | None
    close_date: date | None
    last_activity_at: datetime | None
    days_in_stage: int | None
    days_since_last_activity: int | None
    has_decision_maker: bool | None
```

### Issue (Pydantic)

```python
class Issue(BaseModel):
    rule_id: str
    severity: Literal["high", "medium", "low"]
    message: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
```

### IssueSummary (Pydantic)

```python

class IssueSummary(BaseModel):
    opportunity_id: str
    opportunity_name: str
    owner_email: str
    priority: Literal["high", "medium", "low"]
    issues: list[Issue]
    context: OpportunityContext
    suggested_action: str | None
```

### PipelineState (TypedDict for LangGraph)

```python
class PipelineState(TypedDict):
    companies: list[dict]
    people: list[dict]
    opportunities: list[dict]
    activities: list[dict]
    contexts: list[OpportunityContext]
    issue_summaries: list[IssueSummary]
    briefs: dict[str, str]              # owner_email → brief text
    escalations: dict[str, str]         # manager_email → escalation text
    action_retry_count_by_opp: dict[str, int]  # opportunity_id -> retries used (0..2)
    run_id: str
    errors: list[str]
```

---

## Twenty CRM Integration (GraphQL)

### Queries

Four parallel queries, one per entity:

- **Companies:** `id`, `name`
- **People:** `id`, `name`, `email`, `company { id }`
- **Opportunities:** `id`, `name`, `amount`, `stage`, `closeDate`, `createdAt`, `updatedAt`, `pointOfContact { id }`, `company { id }`
- **Activities/Tasks:** `id`, `type`, `createdAt`, `assignee { id }`, `opportunity { id }`

These fields are validated against the "Validated Against" contract above. The normalizer maps Twenty's field conventions to our `OpportunityContext` model and is the only place that should change when schema fields evolve.

### Client Design

- Base URL: `TWENTY_API_URL` + `/api` (GraphQL endpoint)
- Auth: `Authorization: Bearer TWENTY_API_KEY` header
- Use `httpx` with async support for parallel fetches
- Pagination: handle Twenty's cursor-based pagination for large datasets

---

## Hygiene & Risk Rules

### rules.yaml structure

```yaml
rules:
  stale_in_stage:
    enabled: true
    default_days: 14
    by_stage:
      Qualification: 21
      Negotiation: 7
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
      Proposal: true
      Negotiation: true
    severity: low
```

### Rule evaluation

`rules.py` loads the YAML config at startup and exposes:

```python
def evaluate_opportunity(ctx: OpportunityContext, rules_config: RulesConfig) -> list[Issue]
```

Returns structured `Issue` objects with stable `rule_id` values for routing, fallback action selection, and audit logs.

### Priority scoring

Heuristic combining:
- **Issue severity** from rule config (high/medium/low)
- **Deal amount** (higher = more important)
- **Stage** (later stages = more urgent)
- **Worst issue wins** — priority is the highest severity among all `Issue` objects on the opp

---

## LLM Suggested Actions (DSPy)

### DSPy Signature

```python
class SuggestActionSig(dspy.Signature):
    """Given an opportunity summary and its hygiene issues, propose one concise, practical next action for the AE."""
    opportunity_summary: str = dspy.InputField()
    issues: str = dspy.InputField()
    suggested_action: str = dspy.OutputField(
        desc="One concise, practical next best action for the AE. Be specific — name the action, not the problem."
    )
```

### Quality Gate

The quality gate checks:
1. **Non-empty** — action is not blank or just whitespace
2. **Actionable** — contains a verb (simple heuristic: first word or second word is a verb-like token)
3. **Not a restatement** — action doesn't just echo the issue text (basic similarity check)

On failure: retry up to 2 times, then fall back to a deterministic suggestion based on the highest-severity rule (e.g., `"Update the close date — current date is in the past"` for `close_date_past`).

The quality gate loop operates **per-opportunity** within the `generate_actions`/`validate_actions` graph nodes — not as a graph-level retry of the entire batch. Each opportunity gets up to 2 LLM retries independently before falling back.

Retry bookkeeping is tracked in `PipelineState.action_retry_count_by_opp` so batched runs cannot accidentally share a single global retry counter.

### Fallback

When DSPy is disabled (`LLM_API_KEY` not set) or all retries fail:

```python
FALLBACK_ACTIONS = {
    "stale_in_stage": "Review this deal — it's been in {stage} for {days} days. Update the stage or add a next step.",
    "no_recent_activity": "Log your latest interaction or schedule a follow-up.",
    "close_date_past": "Update the close date — the current one has passed.",
    "close_date_soon_no_activity": "Close date is in {days} days with no recent activity. Confirm timing or push the date.",
    "missing_amount": "Add a deal amount so forecasting is accurate.",
    "missing_close_date": "Set a close date for this opportunity.",
    "missing_decision_maker": "Identify and add a decision maker contact.",
}
```

Fallback selection uses the highest-severity issue's `rule_id` for deterministic mapping, avoiding brittle string matching.

---

## Escalation Routing

### escalation.yaml structure

```yaml
escalation:
  default_manager: vp-sales@demo.com
  overrides:
    alex@demo.com: manager-a@demo.com
    jordan@demo.com: manager-b@demo.com

  # Threshold: an opp is "critical" if priority is high AND amount >= this value
  critical_amount_threshold: 50000
```

### Routing logic

After issue computation:
1. Filter issues where `priority == "high"` AND `amount >= critical_amount_threshold`
2. These are "critical" — generate both an AE brief AND a manager escalation email
3. All other issues go through the normal AE brief path only

Manager escalation email is a condensed format: deal name, amount, stage, issues, and the AE's name — so the manager knows who to follow up with.

---

## Email Delivery (Resend)

### AE Brief format

```
Subject: Your Pipeline Coach brief for 2026-03-30

Hi Alex,

Here are your top 5 pipeline actions for today:

1) Acme Corp Expansion — $120,000 — Stage: Negotiation
   Last activity: 18 days ago
   Close date: 2026-03-15 (PAST)
   Issues:
     - Close date has passed
     - No activity in 18 days (threshold: 7)
   Suggested action: Schedule a call with the Acme team to confirm
   whether this deal is still active and set a realistic close date.

2) ...

Best,
Pipeline Coach
```

### Manager Escalation format

```
Subject: [Escalation] 2 critical deals need attention — 2026-03-30

Hi Jordan's Manager,

The following deals owned by Jordan Lee are flagged as critical:

1) GlobalSoft Migration — $150,000 — Stage: Proposal
   Issues:
     - Stale in Proposal: 28 days (threshold: 14)
     - No activity in 22 days
   AE: Jordan Lee (jordan@demo.com)

Please follow up with Jordan on these deals.

Best,
Pipeline Coach
```

### Rendering

Brief rendering is isolated in `coach/brief.py` as pure functions that take `IssueSummary[]` and return plain text. This keeps the same content reusable for future Slack DMs.

---

## Scheduling & Observability

### Scheduler

- APScheduler with a `CronTrigger` set to `RUN_AT_HOUR` (default: 08:00)
- `run_once.py` for manual/ad-hoc runs
- `__main__.py` starts the scheduler by default, with a `--once` flag for single runs

### Logging

Structured logging (Python `logging` with JSON formatter) capturing:
- **Per-run:** run ID, timestamp, opps scanned, issues found, emails sent/failed
- **Per-issue audit:** opp ID, owner email, rule IDs that fired, suggested action text, run ID

### CLI audit tool

```bash
python -m pipeline_coach.show_recent --owner alex@demo.com
```

Prints the most recent brief and underlying issues for that owner. Reads from a local JSON log file (`data/audit_log.jsonl`).

---

## Docker Compose

```yaml
services:
  twenty-db:
    image: postgres:15
    volumes:
      - twenty_pg_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: twenty
      POSTGRES_USER: twenty
      POSTGRES_PASSWORD: twenty

  twenty:
    image: twentyhq/twenty:latest
    depends_on:
      - twenty-db
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgres://twenty:twenty@twenty-db:5432/twenty
      SERVER_URL: http://localhost:3000
      FRONT_BASE_URL: http://localhost:3000

  pipeline-coach:
    build: .
    depends_on:
      - twenty
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./data:/app/data

  pipeline-coach-smoke:
    build: .
    depends_on:
      - twenty
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./data:/app/data
    command: ["python", "-m", "pipeline_coach.smoke_test"]

volumes:
  twenty_pg_data:
```

### One-command integration smoke test

Run a full-stack smoke check (ingest + rules + action generation path + delivery dry run) with:

```bash
docker compose run --rm pipeline-coach-smoke
```

The smoke command exits non-zero on connectivity/schema/config failures, making it CI-friendly.

---

## Configuration & Secrets

### .env.example

```bash
# Twenty CRM
TWENTY_API_URL=http://twenty:3000
TWENTY_API_KEY=your-twenty-api-key

# Resend
RESEND_API_KEY=your-resend-api-key
EMAIL_FROM=pipeline-coach@yourdomain.com

# LLM (for DSPy)
LLM_API_KEY=your-llm-api-key
LLM_MODEL=gpt-4o-mini

# Scheduling
RUN_AT_HOUR=08

# Optional v1 local-demo privacy controls
AUDIT_REDACT_PII=false
AUDIT_LOG_RETENTION_DAYS=30
```

Secrets in `.env` (gitignored). Rule and escalation config in `config/` (committed). Production note in README: secrets should move to a dedicated secrets manager.

---

## Security & Privacy (Optional for v1 local demo)

The default v1 local-demo mode favors debuggability. Optional controls can be enabled when you want stricter handling:

- **PII handling:** set `AUDIT_REDACT_PII=true` to redact owner emails and names in audit logs/CLI output.
- **Retention:** enforce bounded local retention with `AUDIT_LOG_RETENTION_DAYS` (default 30).
- **Redaction scope:** redact AE/manager identifiers in persisted JSONL while keeping non-PII operational fields (`rule_id`, severity, counts, timestamps).
- **Secrets hygiene:** keep API keys in `.env` only for local demo; use a secret manager in shared/prod environments.

These controls are intentionally optional in v1 so local setup remains simple while still offering a clear path to safer operation.

---

## Seed Script

`scripts/seed_twenty.py` creates via Twenty's GraphQL API:
- 5 companies (Acme Corp, Northwind, GlobalSoft, Brightwave, NimbusHQ)
- 2 AEs (Alex Doe, Jordan Lee) + 2-3 contacts per company
- 20-30 opportunities across stages with injected hygiene issues
- Activities with varied recency (some recent, some stale, some missing)

Outputs a summary and optionally saves IDs to `scripts/seed_output.json`.

---

## Testing Strategy (v1)

**Unit tests + one integration smoke test.** Externals are mocked in unit tests; the smoke test exercises real service wiring in Docker Compose.

| Test file | Covers |
|---|---|
| `test_rules.py` | Rule evaluation against various OpportunityContext fixtures |
| `test_priority.py` | Priority scoring heuristic |
| `test_brief.py` | Brief text rendering |
| `test_quality_gate.py` | LLM output validation logic |
| `test_normalizer.py` | GraphQL response → OpportunityContext mapping |

Smoke test entrypoint:
- `python -m pipeline_coach.smoke_test` (run via `docker compose run --rm pipeline-coach-smoke`)

**Future (v2+):** Full integration suites (multi-scenario) against real Twenty/Resend plus explicit contract tests for GraphQL + email payloads.

---

## README Notes

The README should document:
- Quickstart (`.env`, `docker compose up`, seed, run)
- Manual run (`python -m pipeline_coach --once`)
- How the scheduler runs daily
- How to tune rules (`config/rules.yaml`) and escalation (`config/escalation.yaml`)
- Secrets management (`.env` local only; production uses secrets manager)
- Testing: v1 has unit tests with mocked externals plus a compose smoke test; full integration/contract suites are planned for v2
- Smoke testing: one-command compose smoke check (`docker compose run --rm pipeline-coach-smoke`)
- Architecture: monolith package for v1; future versions may decompose into services if scale demands it
- Slack: intentionally not implemented; message rendering is designed to be reusable for Slack DMs
- Agent identity and read-only behavior
- License: Apache 2.0

---

## Out of Scope (v1)

- Slack notifications
- CRM write-back (creating tasks/notes in Twenty)
- DSPy prompt optimization (no training examples yet)
- Multi-tenant / multi-CRM support
- Web UI or dashboard
- Full integration suites / contract tests
