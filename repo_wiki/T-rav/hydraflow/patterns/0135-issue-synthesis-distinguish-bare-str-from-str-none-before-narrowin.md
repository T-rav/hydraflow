---
id: 0135
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.620468+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Distinguish bare `str` from `str | None` before narrowing a field type

Narrowing a bare `str` field to a StrEnum is safe when all stored values already conform. Narrowing a union like `str | None` requires union narrowing, not direct replacement.

Example: grep all state.json consumers and call sites exhaustively before narrowing; treat union fields separately.

**Why:** Narrowing a union type as if it were a bare type causes `ValidationError` on load for any stored `None` values.
