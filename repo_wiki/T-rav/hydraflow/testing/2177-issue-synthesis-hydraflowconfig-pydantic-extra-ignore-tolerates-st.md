---
id: 2177
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.393126+00:00
status: superseded
corroborations: 1
supersedes: 2048
superseded_by: 2322
---

# HydraFlowConfig pydantic extra=ignore tolerates stale keys

Removing a config field from `HydraFlowConfig` is back-compatible: pydantic `extra='ignore'` silently drops unknown keys in persisted settings JSON. Pin this with a stale-key tolerance test.

Example: after excising `memory_auto_approve`, a persisted settings JSON carrying the key degrades silently rather than raising.

**Why:** Operators' persisted configs survive flag removal without manual migration — but only if the tolerance is explicitly tested, not assumed.
