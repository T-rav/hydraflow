---
id: 0009
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.313084+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Distinguish bare `str` from `str | None` before narrowing a field type

Narrowing a bare `str` field to a StrEnum is safe when all stored values already conform. Narrowing a union like `str | None` requires union narrowing, not direct replacement.

Example: grep all state.json consumers and call sites exhaustively before narrowing; treat union fields separately.

**Why:** Narrowing a union type as if it were a bare type causes `ValidationError` on load for any stored `None` values.
