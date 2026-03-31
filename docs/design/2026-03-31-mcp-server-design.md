# Pipeline Coach MCP Server — Design Spec

## Overview

An MCP (Model Context Protocol) server that exposes Pipeline Coach's pipeline intelligence as tools and resources. Users can query deal health, run hygiene analysis, and inspect audit history from any MCP client (Claude Code, Claude Desktop, Cursor, etc.).

This is the **open-source** MCP server. It uses stdio transport and connects to a local Twenty CRM instance. HTTP transport with OAuth 2.1 is an Enterprise feature.

---

## Validated Against

- **MCP SDK:** `mcp` Python SDK (pin to latest stable at implementation time; confirm tool annotations and structured output support)
- **Twenty CRM:** self-hosted Docker image `twentycrm/twenty:latest` (same instance as Pipeline Coach main)
- **Tested clients:** Claude Code (`~/.claude.json`), Cursor (`.cursor/mcp.json`)
- **Twenty rate limit:** confirm against your deployment; self-hosted default observed at ~100 requests/60s during Pipeline Coach testing, but this is not documented by Twenty and may vary by version or plan

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Location | In-repo subpackage `pipeline_coach/mcp/` | Shares internal types directly, ships as part of same package |
| Transport | stdio | Standard for local MCP servers; Claude Code, Cursor, Claude Desktop all support it |
| Auth | None (stdio) | Parent process owns the connection; no auth needed for local use |
| Data freshness | Always live from Twenty | No cache layer in v1; rate limit sufficient for interactive use |
| LLM in tools | Opt-in per call | `analyze_pipeline` and `get_deal_overview` accept `use_llm` parameter, default false |
| Protocol version | 2025-03-26+ | Use tool annotations (readOnlyHint), structured tool output |
| SDK | `mcp` Python SDK | Official MCP Python SDK, handles stdio transport and protocol |

---

## Security and Privacy

All tools surface CRM data including PII (owner emails, deal names, company names, amounts). The trust model for v1:

- **stdio transport** — the MCP client (Claude Code, Cursor) runs on the same machine as the server. The local user already has access to the `.env` file with the Twenty API key. No additional attack surface.
- **Audit log** — `get_audit_history` and `get_run_details` read from local `data/audit_log.jsonl`, which may contain owner emails unless `AUDIT_REDACT_PII=true` was set during the pipeline run that created those records.
- **No network exposure** — stdio servers do not listen on a port. There is no remote access path in v1.

For shared/team access with auth boundaries, see Enterprise (HTTP transport + OAuth 2.1).

---

## Tools

### `analyze_pipeline`

Run full hygiene analysis on all open opportunities.

**Parameters:**
- `use_llm` (boolean, optional, default: false) — generate LLM-powered action suggestions instead of deterministic templates

**Returns:** Structured JSON with:
- `run_id`: string
- `total_opportunities`: number (scanned, excluding terminal stages)
- `issues_found`: number
- `summaries`: array of issue summaries, each with:
  - `opportunity_name`, `company_name`, `owner_email`, `stage`, `amount`
  - `priority` (high/medium/low)
  - `issues` array (rule_id, severity, message)
  - `suggested_action`, `action_rationale`
  - `crm_link` (deep link to opportunity in Twenty)

**Example return (trimmed):**
```json
{
  "run_id": "mcp-a1b2",
  "total_opportunities": 10,
  "issues_found": 3,
  "summaries": [
    {
      "opportunity_name": "Acme Expansion",
      "company_name": "Acme Corp",
      "owner_email": "alex@demo.com",
      "stage": "PROPOSAL",
      "amount": 120000.0,
      "priority": "high",
      "issues": [
        {"rule_id": "close_date_past", "severity": "high", "message": "Close date 2026-03-15 is in the past"}
      ],
      "suggested_action": "Update the close date — the current one has passed.",
      "action_rationale": "Past close dates reduce forecast accuracy and hide true pipeline health.",
      "crm_link": "http://localhost:3000/object/opportunity/abc-123"
    }
  ]
}
```

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

**Implementation:** Reuses `normalize_opportunities`, `evaluate_opportunity`, `compute_priority`, `generate_suggested_action_with_rationale` from existing modules. Does NOT send emails. Deep links use `CRM_PUBLIC_URL` if set, otherwise `TWENTY_API_URL` (same logic as `run_once.py`).

---

### `get_deal_overview`

Deep dive on a single opportunity.

**Parameters:**
- `query` (string, required) — opportunity name or ID (fuzzy match on name)
- `use_llm` (boolean, optional, default: false)

**Returns:**
- `opportunity`: full OpportunityContext (name, stage, amount, owner, company, close date, last activity, days in stage, has decision maker)
- `issues`: array of Issue objects (or empty if clean)
- `priority`: high/medium/low (or null if no issues)
- `suggested_action`, `action_rationale` (or null if no issues)
- `crm_link`: deep link to Twenty
- `match_info`: object with `matched_name`, `match_type` ("exact_id", "exact_name", "substring"), and `other_matches` array (names of other partial matches, if any)

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

**Implementation:** Fetches all data from Twenty, normalizes, finds matching opportunity, runs rules + priority + optional action generation on that single deal.

---

### `get_company_overview`

All open opportunities for a specific company with their health status. This tool always uses deterministic actions (`use_llm` does not apply).

**Parameters:**
- `company_name` (string, required) — fuzzy match

**Returns:**
- `company_name`: resolved name
- `total_opportunities`: number
- `healthy`: number (no issues)
- `flagged`: number (has issues)
- `total_pipeline_value`: sum of amounts
- `opportunities`: array, each with:
  - `name`, `stage`, `amount`, `owner_email`, `close_date`
  - `status`: "healthy" or "flagged"
  - `issues`: array (only if flagged)
  - `suggested_action` (only if flagged, always deterministic)
  - `crm_link`
- `match_info`: object with `matched_name`, `match_type`, `other_matches`

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

---

### `get_deal_issues`

Check a single opportunity for hygiene issues. Lighter than `get_deal_overview` — just issues, no action generation.

**Parameters:**
- `query` (string, required) — opportunity name or ID

**Returns:**
- `opportunity_name`, `stage`, `amount`
- `issues`: array of Issue objects
- `priority`: high/medium/low or null
- `match_info`: same structure as above

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

---

### `list_stale_deals`

Quick filter: opportunities past their stale-in-stage threshold.

**Parameters:**
- `min_days` (integer, optional) — additional filter applied on top of rule logic. The rule engine evaluates `stale_in_stage` using per-stage thresholds from `rules.yaml` (e.g., PROPOSAL: 7 days, default: 14 days). If `min_days` is provided, only deals stale for at least `min_days` are returned (post-filter, does not override per-stage thresholds).

**Returns:**
- `count`: number
- `deals`: array with `name`, `company_name`, `stage`, `days_in_stage`, `threshold` (the per-stage threshold that triggered), `owner_email`, `crm_link`

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

---

### `get_audit_history`

Recent pipeline run summaries.

**Parameters:**
- `limit` (integer, optional, default: 10) — number of recent runs to return

**Returns:**
- `runs`: array with `run_id`, `timestamp`, `opportunities_with_issues`, `emails_sent`, `emails_failed`, `errors` (array of error strings from the run record)

Note: these are audit snapshots from `data/audit_log.jsonl`. The `errors` field is the raw array from the run record written by `write_audit_record` in `logger.py`. No Twenty API calls.

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

---

### `get_run_details`

Full details for a specific pipeline run.

**Parameters:**
- `run_id` (string, required)

**Returns:**
- `run`: run summary record (same fields as `get_audit_history` entries)
- `issues`: array of audit issue records for that run. These are audit snapshots with `opportunity_id`, `opportunity_name`, `owner_email`, `priority`, `rule_ids` (array of strings), `suggested_action`, `action_rationale`. Note: these are lighter than live Issue objects from the rule engine — they contain `rule_ids` (strings) not full Issue models with `severity` and `details`.
- `errors`: array of error strings (from the run record)

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

**Implementation:** Reads from `data/audit_log.jsonl`. No Twenty API calls.

---

### `get_rules_config`

Show current hygiene rule configuration.

**Parameters:** none

**Returns:**
- `excluded_stages`: array
- `rules`: object with each rule's enabled status, thresholds, severity

**Tool annotations:** `readOnlyHint: true`, `idempotentHint: true`

**Implementation:** Reads `config/rules.yaml`.

---

## Resources

| URI | Name | Description |
|---|---|---|
| `pipelinecoach://config/rules` | Rules Configuration | Current rules.yaml content |
| `pipelinecoach://config/escalation` | Escalation Configuration | Current escalation.yaml content |
| `pipelinecoach://audit/latest` | Latest Run Summary | Most recent pipeline run summary from audit log |

Resource URIs use a custom `pipelinecoach://` scheme specific to this server. Resources are read-only. No resource subscriptions in v1.

---

## Architecture

```
pipeline_coach/mcp/
├── __init__.py
├── __main__.py        # Entry point: python -m pipeline_coach.mcp
├── server.py          # MCP server setup, stdio transport, tool/resource registration
├── tools.py           # Tool handler functions (analyze, overview, issues, audit)
└── helpers.py         # Shared: Twenty data fetching, fuzzy matching, context building
```

### Data flow

```
MCP Client (Claude Code / Cursor)
  ↓ stdio (JSON-RPC)
server.py — routes tool calls
  ↓
tools.py — tool handler functions
  ↓
helpers.py — fetch from Twenty, normalize, evaluate
  ↓
Existing modules:
  pipeline_coach/ingestion/twenty_client.py
  pipeline_coach/ingestion/normalizer.py
  pipeline_coach/hygiene/rules.py
  pipeline_coach/hygiene/priority.py
  pipeline_coach/coach/actions.py
  pipeline_coach/config.py
```

### CRM deep links

All tools that return `crm_link` use the same logic as `run_once.py`: prefer `CRM_PUBLIC_URL` env var if set, otherwise fall back to `TWENTY_API_URL`. This keeps Docker, email, and MCP links consistent. Link format: `{base}/object/opportunity/{id}`.

### Server lifecycle

1. On startup: load `.env` (with `override=True`), initialize `TwentyClient`, load `RulesConfig` and `EscalationConfig`
2. Keep client and config in server state (module-level or server context)
3. Each tool call uses the shared client to fetch live data from Twenty
4. DSPy configured on startup only if `LLM_API_KEY` is set
5. On shutdown: close `TwentyClient`

### Fuzzy matching

`get_deal_overview`, `get_deal_issues`, `get_company_overview`, and `list_stale_deals` (for company filtering, if added) accept name queries. Matching strategy:
1. Exact ID match (if query looks like a UUID)
2. Case-insensitive exact name match
3. Case-insensitive substring match
4. If multiple matches on substring: return the first match, include `match_info.other_matches` with names of up to 5 other matches so the client can disambiguate

No external fuzzy matching library. Simple string operations.

---

## Entry point

```bash
# Run as MCP server (stdio)
python -m pipeline_coach.mcp

# Claude Code config (~/.claude.json or project .mcp.json)
{
  "mcpServers": {
    "pipeline-coach": {
      "command": "python",
      "args": ["-m", "pipeline_coach.mcp"],
      "cwd": "/path/to/pipeline-coach",
      "env": {
        "TWENTY_API_URL": "http://localhost:3000",
        "TWENTY_API_KEY": "your-key"
      }
    }
  }
}
```

---

## Dependencies

Add `mcp` as an optional extra to keep the core install lighter:

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.6.0",
]
```

Install with: `pip install -e ".[mcp]"` or `pip install -e ".[dev,mcp]"`

All existing `pipeline_coach` modules are used directly — no new external dependencies beyond the MCP SDK.

---

## Testing

Unit tests for tool handlers with mocked Twenty client:
- `test_analyze_pipeline` — returns structured results, respects `use_llm` flag
- `test_get_deal_overview` — exact match, substring match, not found, ambiguity (multiple matches returns `other_matches`)
- `test_get_company_overview` — returns grouped deals, handles unknown company, no `use_llm` parameter
- `test_get_deal_issues` — returns issues for flagged deal, empty for clean deal
- `test_list_stale_deals` — filters by rule threshold, respects `min_days` post-filter
- `test_get_audit_history` — reads JSONL, respects limit, returns `errors` array not count
- `test_get_run_details` — returns matching run with audit issue snapshots, handles unknown run_id
- `test_get_rules_config` — returns parsed config
- `test_fuzzy_matching` — UUID match, exact name, substring, multiple matches
- `test_crm_link_uses_public_url` — verifies `CRM_PUBLIC_URL` takes precedence over `TWENTY_API_URL`

---

## Docker Compose

Add a new service:

```yaml
pipeline-coach-mcp:
  build: .
  depends_on:
    twenty:
      condition: service_healthy
  env_file:
    - .env
  volumes:
    - ./config:/app/config
    - ./data:/app/data
  command: ["python", "-m", "pipeline_coach.mcp"]
  stdin_open: true
```

Note: stdio MCP servers in Docker are primarily for testing. In practice, users run the MCP server on the host with `python -m pipeline_coach.mcp`.

---

## Out of Scope (v1)

- HTTP transport (Streamable HTTP)
- OAuth 2.1 / progressive authorization
- Resource subscriptions
- MCP Tasks (long-running operations)
- Sampling (server requesting LLM completions from client)
- Write operations (creating tasks, updating opportunities)
- Elicitation (requesting user input mid-tool-call)
- Response caching / TTL
