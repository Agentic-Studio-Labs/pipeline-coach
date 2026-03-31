# Pipeline Coach – RevOps Pipeline Hygiene & Forecast Coach

## Overview

Build a local “Pipeline Coach” that connects to a self‑hosted Twenty CRM instance, scans pipeline data daily, detects hygiene/risk issues, and sends each opportunity owner a concise daily **email** with prioritized actions using **Resend**. Slack integration is a **future TODO**.

Pipeline Coach uses **LangGraph** for workflow orchestration (as a small state machine) and **DSPy** for the LLM component that proposes human‑readable “next best actions” on each opportunity.

---

## 1. Architecture

**Components**

- **Twenty CRM (self‑hosted)**
  - Runs via Docker + Postgres.
  - Real CRM objects: Companies, People, Opportunities, Activities.

- **RevOps Agent service ("Pipeline Coach")**
  - Language: Python (assumed).
  - Uses **LangGraph** (on top of LangChain) to model the workflow as a small state machine:
    - Nodes: `fetch_from_twenty` → `compute_issues` → `generate_briefs` → `send_emails`.
    - Clear transitions, retries, and logging.
  - Modules:
    - `ingestion` – fetch data from Twenty.
    - `hygiene` – apply rules + optional LLM reasoning.
    - `coach` – generate briefs and send via Resend.
    - `scheduler` – run the pipeline daily.

- **Email delivery**
  - **Resend** API for sending daily briefs (no SMTP).

- **(Future)** Slack integration
  - Not implemented in v1; design message formats so they can later be reused in Slack DMs.

---

## 2. Local Infrastructure

### docker-compose.yml

Define services:

- `twenty-db` – Postgres (persistent volume).
- `twenty` – Twenty CRM app connected to `twenty-db`.
- `revops-agent` – custom service that:
  - Has network access to `twenty`.
  - Reads env vars for Twenty URL/API key, Resend API key, LLM key, etc.

**Networking**

- `revops-agent` can reach `http://twenty:PORT`.

---

## 3. Configuration & Secrets Management

Use **environment variables** and a local `.env` file that is **not committed**:

- `TWENTY_API_URL`
- `TWENTY_API_KEY`
- `RESEND_API_KEY`
- `EMAIL_FROM` (verified in Resend)
- `LLM_API_KEY` (if using an external model)
- Hygiene thresholds:
  - `STALE_STAGE_DAYS`
  - `NO_ACTIVITY_DAYS`
  - `CLOSE_DATE_SOON_DAYS`
- Scheduling:
  - `RUN_AT_HOUR` (e.g., `08`)

**Secrets approach**

- `.env` loaded by Docker/app (e.g., `python-dotenv`), but:
  - `.env` is in `.gitignore`.
  - Provide `.env.example` with placeholder values.
- Note in README:
  - For production, secrets would live in a dedicated manager (Vault, Doppler, cloud secrets) and be injected as env vars. For this project, keep `.env` local only.

---

## 4. Twenty CRM Integration

### Data model (minimum fields)

From Twenty, fetch:

- **Companies**
  - `id`, `name`
- **People**
  - `id`, `email`, `name`, `company_id`
- **Opportunities**
  - `id`, `name`, `amount`, `stage`, `owner_id`, `company_id`
  - `close_date`
  - `created_at`, `updated_at`
- **Activities / Tasks**
  - `id`, linked opportunity/company/person
  - `type` (call, email, meeting, etc.)
  - `created_at` or `activity_date`

### API client

Implement a small Twenty API client:

- Base URL: `TWENTY_API_URL`
- Auth: `TWENTY_API_KEY` header.
- Endpoints (adapt to actual docs):
  - `GET /rest/companies`
  - `GET /rest/people`
  - `GET /rest/opportunities`
  - `GET /rest/tasks` (or activities equivalent)

Normalize into an internal `OpportunityContext`:

```python
OpportunityContext = {
  "id": str,
  "name": str,
  "amount": float | None,
  "stage": str,
  "owner_email": str,
  "owner_name": str | None,
  "company_name": str | None,
  "close_date": date | None,
  "last_activity_at": datetime | None,
  "days_in_stage": int | None,
  "days_since_last_activity": int | None,
  "has_decision_maker": bool | None
}
```

---

## 5. Hygiene & Risk Logic

### Deterministic rules

Function: `evaluate_opportunity(ctx: OpportunityContext) -> IssueSummary`.

Rules (thresholds from env):

1. **Stale in stage**
   - `days_in_stage > STALE_STAGE_DAYS`.

2. **No recent activity**
   - `days_since_last_activity > NO_ACTIVITY_DAYS`.

3. **Close date problems**
   - Close date in the past.
   - Close date within `CLOSE_DATE_SOON_DAYS` and `days_since_last_activity > NO_ACTIVITY_DAYS`.

4. **Missing critical fields**
   - `amount` is null / zero.
   - `close_date` is null.
   - (Optional) `has_decision_maker` is false.

5. **Inconsistent updates**
   - (Optional) amount changed recently but stage unchanged for long (if change history is available).

Return:

```python
IssueSummary = {
  "opportunity_id": str,
  "owner_email": str,
  "priority": "high" | "medium" | "low",
  "issues": [str],
  "context": OpportunityContext,
  "suggested_action": str | None
}
```

Priority heuristic: bigger amount + later stage + worse hygiene → higher priority.

---

## 6. Optional LLM Reasoning with DSPy

For the `suggested_action` field, use **DSPy** to keep the LLM component structured and easy to improve over time.

- Install DSPy in the `revops-agent` container.
- Define a DSPy `Signature` and module, for example:

```python
import dspy

class OpportunityContextSig(dspy.Signature):
    """Summarize an opportunity and propose a next best action."""
    opportunity_summary: str = dspy.InputField()
    issues: str = dspy.InputField()  # bullet list as text
    suggested_action: str = dspy.OutputField(
        desc="One concise, practical next best action for the AE."
    )

SuggestAction = dspy.Predict(OpportunityContextSig)
```

- In the hygiene pipeline, after applying deterministic rules:

```python
suggest_action = SuggestAction()

def add_suggested_action(ctx: OpportunityContext, issues: list[str]) -> str | None:
    if not issues:
        return None
    if not LLM_API_KEY:  # or a DSPY_ENABLED flag
        return default_suggestion(issues)

    summary = render_context_summary(ctx)  # short text: stage, amount, company, last activity, close date
    issues_text = "\n".join(f"- {i}" for i in issues)

    result = suggest_action(
        opportunity_summary=summary,
        issues=issues_text,
    )
    return result.suggested_action.strip() if result.suggested_action else None
```

- The rest of the hygiene logic (rule firing, prioritization) remains deterministic.
- Architecturally: **LangGraph** handles the overall workflow and state machine (`fetch_from_twenty` → `compute_issues` → `generate_briefs` → `send_emails`), while **DSPy** is used only for the small, typed LLM module that turns structured context + issues into a human‑friendly suggested action.

---

## 7. Coach Agent – Emails via Resend

### Grouping

- Group `IssueSummary` by `owner_email`.
- For each owner, sort their issues by:
  - Priority (high → low)
  - Amount (desc)
  - Days stale (desc)

### Email delivery (Resend)

Implement `email_client.py`:

```python
def send_pipeline_brief(to_email: str, subject: str, body_text: str) -> None:
    # Use RESEND_API_KEY from env
    # Call Resend's emails.send API with:
    #   from: EMAIL_FROM
    #   to: [to_email]
    #   subject: subject
    #   text: body_text
    ...
```

Per owner:

- Subject: `Your Pipeline Coach brief for YYYY-MM-DD`
- From: `EMAIL_FROM`
- To: `owner_email`

Body (plain text):

```text
Hi <OwnerName>,

Here are your top <N> pipeline actions for today:

1) <OpportunityName> – $<Amount> – Stage: <Stage>
   - Company: <CompanyName>
   - Last activity: <LastActivityAt or "No activity recorded">
   - Close date: <CloseDate or "Not set">
   - Issues:
     * <Issue 1>
     * <Issue 2>
   Suggested action: <SuggestedAction or a generic suggestion>

2) ...

Best,
Pipeline Coach
```

Keep the rendering function isolated so the same content can later be reused in Slack DMs.

### TODO: Slack integration (future)

- Add comments in code + README:
  - `# TODO: Add Slack bot integration that sends the same briefs as DMs.`
- Design rendering with Slack in mind (easily convertible to Markdown/blocks).

---

## 8. LangGraph Workflow

Model the pipeline as a LangGraph state machine:

- **Nodes**
  - `fetch_from_twenty`:
    - Input: empty or last run time.
    - Output: list of `OpportunityContext`.
  - `compute_issues`:
    - Input: `OpportunityContext[]`
    - Output: `IssueSummary[]` (including optional `suggested_action` via DSPy).
  - `generate_briefs`:
    - Input: `IssueSummary[]`
    - Output: `Dict[owner_email, BriefText]`
  - `send_emails`:
    - Input: `Dict[owner_email, BriefText]`
    - Output: summary (sent, failures).

- **Edges**
  - `start` → `fetch_from_twenty` → `compute_issues` → `generate_briefs` → `send_emails` → `end`.

- Add logging and simple retry (e.g., if Resend call fails for one owner, log and continue).

---

## 9. Scheduling & Logging

- Use a simple scheduler:
  - e.g., APScheduler, or a small loop that waits until `RUN_AT_HOUR` and then runs once per day.
- Daily job:
  1. Run LangGraph pipeline from `start` to `end`.
  2. Log:
     - Timestamp
     - Opportunities scanned
     - Issues found
     - Emails attempted/sent
  3. On failures, log errors clearly and continue with other owners.

- Optional: store last run + issues in a local DB table or JSON file.

---

## 10. Seed / Setup Script for Sample Data

Create `scripts/seed_twenty.py` using Twenty API:

1. **Config**
   - Uses `TWENTY_API_URL`, `TWENTY_API_KEY` from env.

2. **Create sample Companies**
   - `Acme Corp`, `Northwind`, `GlobalSoft`, `Brightwave`, `NimbusHQ`.

3. **Create People**
   - AEs:
     - `Alex Doe` – `alex@demo.com`
     - `Jordan Lee` – `jordan@demo.com`
   - Contacts:
     - 2–3 per company with realistic names/emails.

4. **Create Opportunities**
   - 20–30 opps across stages:
     - `Qualification`, `Discovery`, `Proposal`, `Negotiation`, `Closed Won`, `Closed Lost`.
   - Mix:
     - Amounts: 5k–200k.
     - Owners: Alex / Jordan.
     - Close dates: some past, some within 7 days, some >30 days out.
     - Inject hygiene issues:
       - Missing close dates.
       - Missing amounts.
       - Very old created_at with no activities.

5. **Create Activities/Tasks**
   - For each opp:
     - Some with recent activity (last 3–5 days).
     - Some with last activity 20–60 days ago.
     - Some with none.

6. **Output**
   - Print: `Created X companies, Y people, Z opportunities, W activities.`
   - Optionally save IDs to `seed_output.json`.

---

## 11. Observability & Security

### Agent activity visibility

- Log each run with:
  - Timestamp and run ID
  - Number of opportunities scanned
  - Number of issues found
  - Number of emails sent vs failed
- Store per-issue audit records with:
  - Opportunity ID
  - Owner email
  - Rule IDs that fired (e.g., RULE_STALE_STAGE, RULE_NO_ACTIVITY)
  - Suggested action text (if any)
  - Run ID / timestamp
- Provide a simple CLI command (or endpoint), e.g.:
  - `python -m pipeline_coach.show_recent --owner alex@demo.com`
  - This prints the most recent brief and underlying issues for that owner.

> This basic observability allows you to answer “what did the agent do, when, and why?” without heavy tooling.

### Agent identity & permissions

- **Dedicated agent identity**
  - In Twenty, optionally create a pseudo-user such as `Pipeline Coach` or `pipeline-coach@demo.com`.
  - Use this identity to represent any future automation inside the CRM (e.g., if the agent later writes tasks/notes, they can be clearly attributed to Pipeline Coach rather than a real human user).

- **Read-only behavior in v1**
  - The API key used by Pipeline Coach should have the minimum scopes required:
    - Read access to companies, people, opportunities, and activities.
  - In v1, Pipeline Coach is strictly **read-only** with respect to Twenty:
    - It never edits or creates CRM records.
    - All output is delivered as email suggestions for humans to review and act on.

- **Principle of least privilege**
  - Do not request access to modules that are not needed (e.g., admin/billing areas if present).
  - Keep secrets (Twenty API key, Resend API key, LLM key) in environment variables via a local `.env` that is not checked into version control; in a production setting, these would move to a dedicated secrets manager.

- **Email sending identity**
  - Use a dedicated email identity via Resend, such as `pipeline-coach@yourdomain`.
  - This makes it easy to filter, audit, and revoke the agent’s communications if needed.

---

## 12. README Notes (summary)

In the repo README, include:

- How to start:

  ```bash
  cp .env.example .env   # fill in TWENTY and RESEND secrets locally
  docker compose up -d   # start Twenty + revops-agent
  python scripts/seed_twenty.py
  ```

- How to run once manually:

  ```bash
  python -m pipeline_coach.run_once
  ```

- How the scheduler runs daily.
- Note on secrets and `.env` (local only; production → secrets manager).
- Note that Slack is intentionally not implemented yet and is a future enhancement.

