---
id: 0361
topic: architecture
source_issue: 11273
source_phase: plan
created_at: 2026-08-15T20:41:55.284223+00:00
status: active
corroborations: 1
---

# Prefer LONG_LLM_CYCLE flag over timeout_cb for watchdog bounds

Two mechanisms extend watchdog bounds: `LONG_LLM_CYCLE = True` (class flag, canonical opt-in) and `timeout_cb` override registered in `src/service_registry.py` (targeted remedy). Use the class flag for general loops; reserve `timeout_cb` for protected loops like `principles_audit_loop.py` (#9639).

**Why:** `timeout_cb` was a constraint-specific workaround for a protected loop; applying it broadly bypasses the canonical path and creates inconsistency with the ~6 sibling loops using the flag.
