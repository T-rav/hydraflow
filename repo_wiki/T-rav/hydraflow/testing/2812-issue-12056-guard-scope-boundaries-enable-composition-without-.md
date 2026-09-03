---
id: 2812
topic: testing
source_issue: 12056
source_phase: plan
created_at: 2026-09-02T21:56:47.139363+00:00
status: active
corroborations: 1
---

# Guard scope boundaries enable composition without collision

check-existing-infra applies only to untracked files in `tests/`, `src/`, `scripts/` roots. Exit 0 immediately (allow) if path is tracked in git or lies outside these roots. Tracked-file overwrites are guard-overwriting-tracked-source's surface (ADR-0016).

Example: untracked `tests/test_event_type_reducer_parity.py` → check for neighbors. Tracked `src/foo.py` → allow (different guard). `docs/` → allow.

**Why:** Clear scope prevents guard overlap and false positives; two guards with disjoint surfaces compose deterministically.
