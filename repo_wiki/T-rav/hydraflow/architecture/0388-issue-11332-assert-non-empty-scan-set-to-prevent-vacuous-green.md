---
id: 0388
topic: architecture
source_issue: 11332
source_phase: plan
created_at: 2026-08-16T10:18:33.580138+00:00
status: active
corroborations: 1
---

# Assert non-empty scan set to prevent vacuous-green architecture guards

Add a guard-the-guard test asserting the scanner finds a non-empty call-site set over live `src/`.

`test_adr0092_restricted_declaration.py` verifies at least one `build_agent_command(...)` call exists, so renaming the function wouldn't make the gate silently green.

**Why:** A rename or refactor that eliminates all matched call sites turns the guard into a no-op that always passes, defeating the entire enforcement layer.
