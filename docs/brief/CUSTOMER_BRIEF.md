# Customer Brief: Pipeline Coach Request

## 1. Background

Our revenue teams rely heavily on our CRM to manage pipeline and forecast accurately. In reality, the data inside the CRM is often messy and out of date:

- Deals sit in stages for weeks without any new activity or clear next steps.
- Critical fields like close dates, deal amounts, and decision makers are frequently missing or wrong.
- AEs are overwhelmed by long lists of opportunities and dashboards, and struggle to know what to focus on each day.
- Forecast reviews turn into manual cleanup sessions instead of strategic conversations.

We want to move from **reactive, manual pipeline hygiene** to a more **proactive, always‑on system** that helps reps and RevOps stay ahead of issues.

---

## 2. Problem Statement

Right now, there is **no consistent way** to:

- Spot stalled or at‑risk deals early.  
- Enforce basic hygiene rules (e.g., “no opp in Proposal with no next meeting scheduled”).  
- Give each AE a short, prioritized list of where to focus **today**.  

Everything depends on individuals remembering to check reports, filter views correctly, and clean up their own data. This leads to:

- Inaccurate forecasts and “surprises” at the end of the month.  
- Wasted time in pipeline review meetings doing manual data clean‑up.  
- Missed follow‑ups on promising deals because they get lost in the noise.  

We need a lightweight way to **continuously monitor CRM data** and surface the most important actions without adding more dashboards or tools for AEs to maintain.

---

## 3. Goals

We are looking for a solution that:

1. **Scans our CRM automatically every day**  
   - Reads opportunities, owners, stages, activity history, and key fields.  
   - Identifies pipeline hygiene problems and risk signals based on simple, configurable rules.

2. **Prioritizes issues at the opportunity and owner level**  
   - Stale deals (too long in stage, no recent activity).  
   - Missing or inconsistent data (no close date, no amount, no decision maker).  
   - Close dates that are unrealistic (in the past, or too soon without activity).

3. **Delivers a concise daily brief to each AE via email**  
   - One email per rep, per day.  
   - Top 5–10 deals that need their attention, with:
     - What’s wrong with each deal (issues).  
     - A simple suggested “next best action” they can take.  

4. **Requires minimal process change**  
   - Reps receive insights in their inbox and act in the CRM as they do today.  
   - No new UI for them to learn in v1.

5. **Sets us up for future automation**  
   - In the future, we may want:
     - Slack notifications instead of, or in addition to, email.  
     - The agent to open tasks/notes directly in the CRM under its own identity.  
     - More advanced “self‑improving” suggestions as we see what works.

---

## 4. Constraints & Preferences

- **CRM**: We are using a self‑hosted instance of Twenty as our CRM system for this project.  
- **Delivery channel (v1)**: Email only (using our existing email sending setup). Slack can be a future enhancement.  
- **Scope of changes**:
  - v1 must be **read‑only** with respect to the CRM: it can read data and send suggestions, but must not modify records.
- **Security & accountability**:
  - The “agent” should have its own identity and API credentials so its activity can be audited.
  - We need basic logging to understand:
    - When it ran.
    - What it scanned.
    - What it recommended.

---

## 5. Desired Outcome

At the end of this engagement, we want:

- A working “Pipeline Coach” service that:
  - Connects to Twenty.
  - Runs daily, identifies issues, and emails AEs a prioritized list of actions.
- A simple way to configure thresholds and rules (e.g., “stale after 14 days”, “no activity after 7 days”).  
- Clear documentation so RevOps and Sales Leadership understand:
  - What the agent is doing.
  - How to tune it.
  - How to turn it off or extend it (e.g., add Slack, more rules, or auto‑created tasks) later.

If successful, this should reduce manual pipeline hygiene work, improve forecast confidence, and give reps a much clearer focus at the start of each day.
