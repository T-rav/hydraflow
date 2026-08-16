---
id: 2708
topic: testing
source_issue: 11332
source_phase: plan
created_at: 2026-08-16T10:18:33.580119+00:00
status: active
corroborations: 1
---

# Treat **kwargs splat as undeclared in keyword-arg presence guards

In AST guards that require a named keyword argument to be present, treat `**kwargs` splats (`keyword.arg is None`) as undeclared.

`test_adr0092_restricted_declaration.py` marks `build_agent_command(**kwargs)` as undeclared for the `restricted=` check because the scanner cannot prove the flag is threaded through.

**Why:** Accepting a splat would let call sites evade the declaration requirement without ever stating ADR-0092 posture at the spawn site.
