---
id: 0051
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.522325+00:00
status: superseded
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
superseded_by: 0092
---

# Distinguish bare `str` from `str | None` before narrowing a field type

Narrowing a bare `str` field to a StrEnum is safe when all stored values already conform. Narrowing a union like `str | None` requires union narrowing, not direct replacement.

Example: grep all state.json consumers and call sites exhaustively before narrowing; treat union fields separately.

**Why:** Narrowing a union type as if it were a bare type causes `ValidationError` on load for any stored `None` values.
