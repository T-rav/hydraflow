---
id: 0093
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.958284+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Distinguish bare `str` from `str | None` before narrowing a field type

Narrowing a bare `str` field to a StrEnum is safe when all stored values already conform. Narrowing a union like `str | None` requires union narrowing, not direct replacement.

Example: grep all state.json consumers and call sites exhaustively before narrowing; treat union fields separately.

**Why:** Narrowing a union type as if it were a bare type causes `ValidationError` on load for any stored `None` values.
