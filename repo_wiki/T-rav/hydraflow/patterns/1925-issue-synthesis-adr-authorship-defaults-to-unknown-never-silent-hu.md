---
id: 1925
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:27.023600+00:00
status: active
corroborations: 1
supersedes: 1827
---

# ADR authorship defaults to UNKNOWN, never silent HUMAN

When classifying ADR authorship, an ADR with no introducing commit must return UNKNOWN with a cited signal — never silently default to HUMAN.

Example: `setpoint/authorship.py` returns HUMAN/AGENT/UNKNOWN, each carrying a cited sha and signal: AGENT = bot-account author email or Claude `Co-Authored-By` trailer; UNKNOWN = no introducing commit found.

**Why:** Silent HUMAN defaults hide missing git history and bias the selection-pressure covariate toward the human bucket.
