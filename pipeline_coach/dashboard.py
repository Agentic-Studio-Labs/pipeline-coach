"""Lightweight audit trail dashboard. No external dependencies beyond stdlib."""

from __future__ import annotations

import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

AUDIT_DIR = Path("data")
PORT = 8080


def _update_audit_dir(path: Path) -> None:
    global AUDIT_DIR  # noqa: PLW0603
    AUDIT_DIR = path


DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pipeline Coach — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --font-body: 'Space Grotesk', system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
    --bg: #0d1117; --surface: #161b22; --surface2: #1c2129;
    --border: rgba(255,255,255,0.06); --border-bright: rgba(255,255,255,0.12);
    --text: #e6edf3; --text-dim: #7d8590;
    --blue: #58a6ff; --blue-dim: rgba(88,166,255,0.1);
    --green: #3fb950; --green-dim: rgba(63,185,80,0.1);
    --orange: #d29922; --orange-dim: rgba(210,153,34,0.1);
    --red: #f85149; --red-dim: rgba(248,81,73,0.1);
    --purple: #bc8cff; --purple-dim: rgba(188,140,255,0.1);
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: var(--bg);
    background-image: radial-gradient(ellipse at 15% 0%, var(--blue-dim) 0%, transparent 45%);
    color: var(--text); font-family: var(--font-body); padding: 40px; min-height: 100vh;
  }
  .container { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 36px; font-weight: 700; letter-spacing: -1px; margin-bottom: 4px; }
  h1 span { color: var(--blue); }
  .subtitle { color: var(--text-dim); font-size: 12px; font-family: var(--font-mono); margin-bottom: 24px; }

  /* Tabs */
  .tabs { display: flex; gap: 0; margin-bottom: 28px; border-bottom: 1px solid var(--border); }
  .tab {
    padding: 10px 24px; font-family: var(--font-mono); font-size: 12px; font-weight: 600;
    color: var(--text-dim); cursor: pointer; border-bottom: 2px solid transparent;
    transition: all 0.2s; text-transform: uppercase; letter-spacing: 1px;
  }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--blue); border-bottom-color: var(--blue); }
  .tab .tab-count {
    font-size: 10px; background: var(--surface2); border-radius: 8px;
    padding: 1px 7px; margin-left: 6px;
  }
  .tab.active .tab-count { background: var(--blue-dim); color: var(--blue); }
  .tab--errors.has-errors { color: var(--red); }
  .tab--errors.has-errors .tab-count { background: var(--red-dim); color: var(--red); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* Stats */
  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
  .stat-label { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px; color: var(--text-dim); margin-bottom: 6px; }
  .stat-value { font-size: 28px; font-weight: 700; }
  .stat-value--green { color: var(--green); }
  .stat-value--red { color: var(--red); }
  .stat-value--blue { color: var(--blue); }
  .stat-value--orange { color: var(--orange); }

  /* Run cards */
  .run-card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    margin-bottom: 12px; overflow: hidden; transition: border-color 0.2s;
  }
  .run-card:hover { border-color: var(--border-bright); }
  .run-card.has-errors { border-color: var(--red-dim); }
  .run-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; cursor: pointer; user-select: none;
  }
  .run-header:hover { background: var(--surface2); }
  .run-id { font-family: var(--font-mono); font-size: 13px; color: var(--blue); font-weight: 600; }
  .run-time { font-family: var(--font-mono); font-size: 11px; color: var(--text-dim); }
  .run-badges { display: flex; gap: 10px; align-items: center; }
  .badge {
    font-family: var(--font-mono); font-size: 10px; font-weight: 600; padding: 3px 10px;
    border-radius: 4px; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .badge--issues { background: var(--orange-dim); color: var(--orange); }
  .badge--sent { background: var(--green-dim); color: var(--green); }
  .badge--failed { background: var(--red-dim); color: var(--red); }
  .badge--errors { background: var(--red-dim); color: var(--red); }
  .chevron { color: var(--text-dim); font-size: 14px; transition: transform 0.2s; }
  .run-card.open .chevron { transform: rotate(90deg); }
  .run-issues { display: none; border-top: 1px solid var(--border); padding: 0 20px; }
  .run-card.open .run-issues { display: block; }

  /* Issue rows */
  .issue-row {
    display: grid; grid-template-columns: 80px 1fr 2fr 2fr;
    gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border);
    font-size: 12px; align-items: start;
  }
  .issue-row:last-child { border-bottom: none; }
  .priority-badge {
    font-family: var(--font-mono); font-size: 10px; font-weight: 600; padding: 2px 8px;
    border-radius: 4px; text-transform: uppercase; text-align: center;
  }
  .priority-badge--high { background: var(--red-dim); color: var(--red); }
  .priority-badge--medium { background: var(--orange-dim); color: var(--orange); }
  .priority-badge--low { background: var(--blue-dim); color: var(--blue); }
  .issue-name { font-weight: 600; }
  .issue-rules code {
    font-family: var(--font-mono); font-size: 10px; background: var(--purple-dim);
    color: var(--purple); padding: 1px 5px; border-radius: 3px; margin-right: 4px;
  }
  .issue-action { color: var(--text-dim); font-style: italic; }

  /* Error cards */
  .error-card {
    background: var(--surface); border: 1px solid var(--red-dim); border-radius: 12px;
    margin-bottom: 12px; padding: 16px 20px;
  }
  .error-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .error-run-id { font-family: var(--font-mono); font-size: 12px; color: var(--blue); font-weight: 600; }
  .error-run-link {
    font-family: var(--font-mono); font-size: 12px; color: var(--blue); font-weight: 600;
    text-decoration: none; border-bottom: 1px dashed var(--blue-dim);
  }
  .error-run-link:hover { border-bottom-color: var(--blue); }
  .run-card.highlight { border-color: var(--blue); box-shadow: 0 0 16px rgba(88,166,255,0.15); }
  .error-time { font-family: var(--font-mono); font-size: 11px; color: var(--text-dim); }
  .error-message {
    background: var(--surface2); border: 1px solid var(--border); border-left: 3px solid var(--red);
    border-radius: 0 8px 8px 0; padding: 10px 14px; margin-bottom: 6px;
    font-family: var(--font-mono); font-size: 11px; line-height: 1.6; color: var(--text);
    word-break: break-word; white-space: pre-wrap;
  }
  .error-category {
    font-family: var(--font-mono); font-size: 9px; font-weight: 600; padding: 2px 8px;
    border-radius: 4px; text-transform: uppercase; letter-spacing: 0.5px;
    display: inline-block; margin-bottom: 8px;
  }
  .error-category--fetch { background: var(--blue-dim); color: var(--blue); }
  .error-category--email { background: var(--orange-dim); color: var(--orange); }
  .error-category--llm { background: var(--purple-dim); color: var(--purple); }
  .error-category--other { background: var(--red-dim); color: var(--red); }

  .empty { text-align: center; padding: 60px 20px; color: var(--text-dim); font-size: 14px; }
  .empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.3; }

  .filter-row { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
  .filter-input {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 14px; color: var(--text); font-family: var(--font-mono); font-size: 12px;
    outline: none; width: 280px;
  }
  .filter-input:focus { border-color: var(--blue); }
  .filter-input::placeholder { color: var(--text-dim); }
  .refresh-btn {
    background: var(--blue-dim); border: 1px solid var(--blue); border-radius: 8px;
    padding: 8px 16px; color: var(--blue); font-family: var(--font-mono); font-size: 11px;
    font-weight: 600; cursor: pointer; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .refresh-btn:hover { background: rgba(88,166,255,0.2); }

  @media (max-width: 768px) {
    body { padding: 20px; }
    .stats-row { grid-template-columns: 1fr 1fr; }
    .issue-row { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="container">
  <h1>Pipeline <span>Coach</span></h1>
  <p class="subtitle">dashboard</p>

  <div class="tabs">
    <div class="tab active" data-tab="audit" onclick="switchTab('audit')">
      Audit Trail <span class="tab-count" id="tab-count-audit">0</span>
    </div>
    <div class="tab tab--errors" data-tab="errors" onclick="switchTab('errors')">
      System Errors <span class="tab-count" id="tab-count-errors">0</span>
    </div>
  </div>

  <!-- AUDIT TRAIL TAB -->
  <div class="tab-panel active" id="panel-audit">
    <div class="stats-row">
      <div class="stat-card"><div class="stat-label">Total Runs</div><div class="stat-value stat-value--blue" id="stat-runs">-</div></div>
      <div class="stat-card"><div class="stat-label">Issues Found</div><div class="stat-value stat-value--orange" id="stat-issues">-</div></div>
      <div class="stat-card"><div class="stat-label">Emails Sent</div><div class="stat-value stat-value--green" id="stat-sent">-</div></div>
      <div class="stat-card"><div class="stat-label">Emails Failed</div><div class="stat-value stat-value--red" id="stat-failed">-</div></div>
    </div>
    <div class="filter-row">
      <input type="text" class="filter-input" id="filter" placeholder="Filter by owner email or opportunity name...">
      <button class="refresh-btn" onclick="loadData()">Refresh</button>
    </div>
    <div id="runs"></div>
  </div>

  <!-- SYSTEM ERRORS TAB -->
  <div class="tab-panel" id="panel-errors">
    <div class="stats-row" style="grid-template-columns: repeat(3, 1fr)">
      <div class="stat-card"><div class="stat-label">Total Errors</div><div class="stat-value stat-value--red" id="stat-total-errors">-</div></div>
      <div class="stat-card"><div class="stat-label">Runs with Errors</div><div class="stat-value stat-value--orange" id="stat-error-runs">-</div></div>
      <div class="stat-card"><div class="stat-label">Last Error</div><div class="stat-value stat-value--blue" id="stat-last-error" style="font-size:14px">-</div></div>
    </div>
    <div class="filter-row">
      <input type="text" class="filter-input" id="error-filter" placeholder="Filter errors by keyword...">
    </div>
    <div id="errors"></div>
  </div>
</div>

<script>
let allData = [];

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${tab}"]`).classList.add('active');
  document.getElementById(`panel-${tab}`).classList.add('active');
}

async function loadData() {
  try {
    const resp = await fetch('/api/audit');
    allData = await resp.json();
    renderAudit();
    renderErrors();
  } catch(e) {
    document.getElementById('runs').innerHTML = '<div class="empty"><div class="empty-icon">&#128269;</div>No audit data yet. Run the pipeline first.</div>';
  }
}

function categorizeError(msg) {
  const m = msg.toLowerCase();
  if (m.includes('fetch_') || m.includes('graphql') || m.includes('twenty') || m.includes('connection')) return 'fetch';
  if (m.includes('email') || m.includes('resend')) return 'email';
  if (m.includes('dspy') || m.includes('llm') || m.includes('predict') || m.includes('openai') || m.includes('anthropic')) return 'llm';
  return 'other';
}

function renderAudit() {
  const filter = document.getElementById('filter').value.toLowerCase();
  const runs = {};
  let totalIssues = 0, totalSent = 0, totalFailed = 0;

  for (const r of allData) {
    if (r.type === 'run') {
      runs[r.run_id] = { ...r, issues: [] };
      totalSent += r.emails_sent || 0;
      totalFailed += r.emails_failed || 0;
    }
  }
  for (const r of allData) {
    if (r.type === 'issue' && runs[r.run_id]) {
      runs[r.run_id].issues.push(r);
      totalIssues++;
    }
  }

  const runList = Object.values(runs).reverse();
  document.getElementById('stat-runs').textContent = runList.length;
  document.getElementById('stat-issues').textContent = totalIssues;
  document.getElementById('stat-sent').textContent = totalSent;
  document.getElementById('stat-failed').textContent = totalFailed;
  document.getElementById('tab-count-audit').textContent = runList.length;

  const container = document.getElementById('runs');
  if (!runList.length) {
    container.innerHTML = '<div class="empty"><div class="empty-icon">&#128269;</div>No audit data yet. Run the pipeline first.</div>';
    return;
  }

  container.innerHTML = runList.map(run => {
    const issues = run.issues.filter(i =>
      !filter || i.owner_email?.toLowerCase().includes(filter) || i.opportunity_name?.toLowerCase().includes(filter)
    );
    if (filter && !issues.length) return '';

    const hasErrors = (run.errors || []).length > 0;
    const issueHtml = issues.map(i => `
      <div class="issue-row">
        <div><span class="priority-badge priority-badge--${i.priority}">${i.priority}</span></div>
        <div class="issue-name">${esc(i.opportunity_name)}</div>
        <div class="issue-rules">${i.rule_ids.map(r => '<code>' + esc(r) + '</code>').join('')}</div>
        <div class="issue-action">${esc(i.suggested_action || 'No action')}</div>
      </div>
    `).join('');

    const time = new Date(run.timestamp).toLocaleString();
    return `
      <div class="run-card ${hasErrors ? 'has-errors' : ''}" onclick="this.classList.toggle('open')">
        <div class="run-header">
          <div>
            <span class="run-id">${esc(run.run_id)}</span>
            <span class="run-time" style="margin-left:12px">${time}</span>
          </div>
          <div class="run-badges">
            <span class="badge badge--issues">${run.opportunities_with_issues} issues</span>
            <span class="badge badge--sent">${run.emails_sent} sent</span>
            ${run.emails_failed ? '<span class="badge badge--failed">' + run.emails_failed + ' failed</span>' : ''}
            ${hasErrors ? '<span class="badge badge--errors">' + run.errors.length + ' errors</span>' : ''}
            <span class="chevron">&#9654;</span>
          </div>
        </div>
        <div class="run-issues">${issueHtml || '<div style="padding:12px 0;color:var(--text-dim);font-size:12px">No issues in this run</div>'}</div>
      </div>
    `;
  }).join('');
}

function renderErrors() {
  const filter = document.getElementById('error-filter').value.toLowerCase();
  const allErrors = [];

  for (const r of allData) {
    if (r.type === 'run' && r.errors && r.errors.length > 0) {
      for (const err of r.errors) {
        allErrors.push({ run_id: r.run_id, timestamp: r.timestamp, message: err });
      }
    }
  }

  const filtered = filter ? allErrors.filter(e => e.message.toLowerCase().includes(filter)) : allErrors;
  const errorRuns = new Set(allErrors.map(e => e.run_id));

  document.getElementById('stat-total-errors').textContent = allErrors.length;
  document.getElementById('stat-error-runs').textContent = errorRuns.size;
  document.getElementById('stat-last-error').textContent = allErrors.length
    ? new Date(allErrors[allErrors.length - 1].timestamp).toLocaleString()
    : 'None';
  document.getElementById('tab-count-errors').textContent = allErrors.length;

  const errTab = document.querySelector('.tab--errors');
  if (allErrors.length > 0) errTab.classList.add('has-errors');
  else errTab.classList.remove('has-errors');

  const container = document.getElementById('errors');
  if (!filtered.length) {
    container.innerHTML = '<div class="empty"><div class="empty-icon">&#9989;</div>No system errors recorded.</div>';
    return;
  }

  container.innerHTML = filtered.reverse().map(e => {
    const cat = categorizeError(e.message);
    const time = new Date(e.timestamp).toLocaleString();
    return `
      <div class="error-card">
        <div class="error-header">
          <div>
            <span class="error-category error-category--${cat}">${cat}</span>
            <a class="error-run-link" style="margin-left:8px" href="#" onclick="event.preventDefault(); jumpToRun('${esc(e.run_id)}')">
              Run ${esc(e.run_id)}
            </a>
          </div>
          <span class="error-time">${time}</span>
        </div>
        <div class="error-message">${esc(e.message)}</div>
      </div>
    `;
  }).join('');
}

function jumpToRun(runId) {
  switchTab('audit');
  setTimeout(() => {
    const cards = document.querySelectorAll('.run-card');
    for (const card of cards) {
      const idEl = card.querySelector('.run-id');
      if (idEl && idEl.textContent === runId) {
        card.classList.add('open', 'highlight');
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => card.classList.remove('highlight'), 3000);
        return;
      }
    }
  }, 50);
}

function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

document.getElementById('filter').addEventListener('input', renderAudit);
document.getElementById('error-filter').addEventListener('input', renderErrors);
loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>
"""


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/audit":
            self._serve_audit_json()
        else:
            self.send_error(404)

    def _serve_html(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode())

    def _serve_audit_json(self) -> None:
        audit_file = AUDIT_DIR / "audit_log.jsonl"
        records = []
        if audit_file.exists():
            with open(audit_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(records).encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline Coach Audit Dashboard")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    parser.add_argument("--audit-dir", type=Path, default=AUDIT_DIR)
    args = parser.parse_args()

    _update_audit_dir(args.audit_dir)

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Dashboard running at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
