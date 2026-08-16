---
id: 1423
topic: gotchas
source_issue: 11296
source_phase: plan
created_at: 2026-08-16T02:48:52.749405+00:00
status: active
corroborations: 1
---

# Tolerate one backend/UI alias: merge vs merged stage key

`tests/test_stage_vocabulary_parity.py` allows exactly one key mismatch: backend `merge` ↔ UI `merged`. All other key differences fail the parity pin. Any future alias must be added explicitly to the tolerated set, not silently.

**Why:** A blanket “keys must match” rule would block on an existing naming wart; an open allowlist would let drift accumulate. One named alias is the narrow gate.
