---
id: 2751
topic: testing
source_issue: 11424
source_phase: plan
created_at: 2026-08-18T04:14:44.048760+00:00
status: active
corroborations: 1
---

# Catalog builders must forward collaborator ports via .get()

MockWorld catalog builders in `tests/scenarios/catalog/loop_registrations.py` receive a `ports` dict and MUST forward collaborator ports with `ports.get("key")` — never `ports[...]` or `setdefault`.

- `_build_escape_ledger` → `auto_diagnoser=ports.get("auto_diagnoser")`
- `_build_diagnostic` → `workspaces=ports.get("workspace")`
- `_build_skill_prompt_eval` → `refine_llm=ports.get("refine_llm")`

**Why:** The harness owns the port dict; direct indexing crashes when a scenario omits the key, and `setdefault` mutates harness-owned state.
