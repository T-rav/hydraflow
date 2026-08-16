---
id: 0387
topic: architecture
source_issue: 11332
source_phase: plan
created_at: 2026-08-16T10:18:33.580129+00:00
status: active
corroborations: 1
---

# Name-matching AST scanners need a separate import-alias guard

When an AST guard matches function calls by name, add a companion test that fails if any `src/` module imports the target with an `asname`.

`test_adr0092_restricted_declaration.py` rejects `from ... import build_agent_command as bac` because the call-site scanner only matches `Name`/`Attribute` nodes named `build_agent_command`.

**Why:** An aliased import silently blinds the scanner, making the guard vacuously pass on call sites it can no longer see.
