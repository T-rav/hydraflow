---
id: 1723
topic: testing
source_issue: 10789
source_phase: plan
created_at: 2026-07-31T02:16:58.506539+00:00
status: superseded
corroborations: 1
superseded_by: 1816
---

# HydraFlowConfig pydantic extra=ignore silently tolerates stale keys

Removing a config field from `HydraFlowConfig` is back-compatible: pydantic `extra='ignore'` silently drops unknown keys in persisted settings JSON. Pin this with a stale-key tolerance test.

- After excising `memory_auto_approve`, a persisted settings JSON carrying the key degrades silently rather than raising.
- P1 test: "Loading a persisted settings JSON that still carries a `memory_auto_approve` key does not raise."

**Why:** Operators' persisted configs survive flag removal without manual migration — but only if the tolerance is explicitly tested, not assumed.
