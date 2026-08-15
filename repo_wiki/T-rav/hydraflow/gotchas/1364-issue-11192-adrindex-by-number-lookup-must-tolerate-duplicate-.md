---
id: 1364
topic: gotchas
source_issue: 11192
source_phase: plan
created_at: 2026-08-15T00:51:35.394353+00:00
status: active
corroborations: 1
---

# ADRIndex by-number lookup must tolerate duplicate ADR numbers

ADR numbers can be duplicated across files — `adr_index` warns and keeps both entries. When writing a by-number helper returning `ADR | None`, never assume a unique match.

Use `next((a for a in ADRIndex(_ADR_DIR).adrs() if a.number == N), None)` and handle multiple matches deterministically rather than relying on single-result assumptions.

**Why:** Assuming uniqueness leads to silent wrong-ADR selection or `StopIteration` errors when duplicate-numbered ADR files coexist in `docs/adr/`.
