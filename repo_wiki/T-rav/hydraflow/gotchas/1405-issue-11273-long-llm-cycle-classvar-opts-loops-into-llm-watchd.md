---
id: 1405
topic: gotchas
source_issue: 11273
source_phase: plan
created_at: 2026-08-15T20:41:55.284183+00:00
status: active
corroborations: 1
---

# LONG_LLM_CYCLE ClassVar opts loops into LLM watchdog bound

Background loops that run unbounded multi-agent LLM work per tick must set `LONG_LLM_CYCLE = True` as a ClassVar in the class body (not `__init__`), declared near `_get_default_interval`. This switches `_cycle_timeout_seconds()` from `loop_watchdog_default_seconds` (7200s) to `loop_watchdog_llm_seconds` (14400s).

Siblings already adopting: `src/issue_refinement_loop.py`, `src/sampled_audit_loop.py`, `src/goal_supervisor_loop.py`.

**Why:** Without the flag, two-agent-per-issue loops like `DiagnosticLoop` get false-killed as watchdog timeouts on busy queues (#11273).
