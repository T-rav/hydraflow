---
id: 0033
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.317893+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Define EVENT_TO_STAGE and SOURCE_TO_STAGE mappings before skip detection

Implement event/worker-to-stage mappings together with skip detection logic — never add a mapping after skip detection is wired.

Example: define `EVENT_TO_STAGE = {...}` and `SOURCE_TO_STAGE = {...}` before the `if event in skip_set: return` guard.

**Why:** Mappings added after the early-return guard are never evaluated, making the new stage silently unreachable.
