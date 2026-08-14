---
id: 2322
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.027016+00:00
status: stale
corroborations: 1
supersedes: 2177
stale_reason: no repo-specific anchor (generic best-practice)
---

# HydraFlowConfig pydantic extra=ignore tolerates stale keys

Removing a config field from `HydraFlowConfig` is back-compatible: pydantic `extra='ignore'` silently drops unknown keys in persisted settings JSON. Pin this with a stale-key tolerance test.

Example: after excising `memory_auto_approve`, a persisted settings JSON carrying the key degrades silently rather than raising.

**Why:** Operators' persisted configs survive flag removal without manual migration — but only if the tolerance is explicitly tested, not assumed.
