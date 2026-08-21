---
id: 0404
topic: architecture
source_issue: 11424
source_phase: plan
created_at: 2026-08-18T04:14:44.048833+00:00
status: stale
corroborations: 1
stale_reason: source issue #11424 closed
---

# Scenario wiring vs production lazy construction in service_registry

`src/service_registry.py` passes `workspaces=` to `DiagnosticLoop` but deliberately leaves `auto_diagnoser` and `refine_llm` as `None` — lazy production construction (live git reads, real `claude` subprocess) is correct there.

Scenario-only wiring changes go in `tests/scenarios/catalog/loop_registrations.py`. Do NOT add production changes to `service_registry.py` to forward these collaborators.

**Why:** Forcing eager construction in production would spawn real subprocesses / git operations at startup, breaking the lazy-init design that defers cost until the gated path actually fires.
