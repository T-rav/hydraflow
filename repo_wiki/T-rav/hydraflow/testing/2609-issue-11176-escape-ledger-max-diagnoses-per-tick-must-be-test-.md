---
id: 2609
topic: testing
source_issue: 11176
source_phase: plan
created_at: 2026-08-14T22:35:54.596968+00:00
status: active
corroborations: 1
---

# escape_ledger_max_diagnoses_per_tick must be test-pinned, not just configured

Rule: Any per-tick budget in `escape_ledger_loop.py` that bounds expensive I/O (git reads + `PRPort.get_issue_labels`) must have a test asserting the cap holds, not merely a config field in `src/config.py`.

Example: 117 eligible aging rows × git + API calls would blow the tick; `escape_ledger_max_diagnoses_per_tick` (default 25, env `HYDRAFLOW_ESCAPE_LEDGER_MAX_DIAGNOSES_PER_TICK`) prevents fan-out and the walk resumes next tick.

**Why:** A configured but untested ceiling can silently regress under refactoring, causing tick timeouts when the aging surface grows.
