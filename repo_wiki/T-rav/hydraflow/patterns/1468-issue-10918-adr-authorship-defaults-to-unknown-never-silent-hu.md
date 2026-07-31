---
id: 1468
topic: patterns
source_issue: 10918
source_phase: plan
created_at: 2026-07-31T15:55:12.930279+00:00
status: active
corroborations: 1
---

# ADR authorship defaults to UNKNOWN, never silent HUMAN

When classifying ADR authorship, an ADR with no introducing commit must return UNKNOWN with a cited signal — never silently default to HUMAN.

`setpoint/authorship.py` returns HUMAN/AGENT/UNKNOWN, each carrying a cited sha and signal:
- AGENT: bot-account author email or Claude `Co-Authored-By` trailer
- UNKNOWN: no introducing commit found

**Why:** Silent HUMAN defaults hide missing git history and bias the selection-pressure covariate toward the human bucket.
