---
id: 0378
topic: architecture
source_issue: 11322
source_phase: plan
created_at: 2026-08-16T09:00:07.880196+00:00
status: active
corroborations: 1
---

# Architecture guards: AST-scan src/, no hardcoded module lists

Architecture guard tests under `tests/architecture/` should AST-scan `src/**/*.py` at runtime rather than maintaining a hardcoded module list.

The ADR-0092 guard (`tests/architecture/test_adr0092_issue_derived_spawns_restricted.py`) verifies:
- Every `build_agent_command` call passes `restricted=` OR lives in an ADR-named exempt module
- Every ADR-exempt module still contains a live call site (anti-rot)
- A synthetic spawn omitting `restricted=` and absent from the ADR fails the guard

**Why:** Hardcoded lists rot when modules are renamed or added; AST scanning with ADR-sourced exemptions keeps the guard self-updating and the ADR authoritative.
