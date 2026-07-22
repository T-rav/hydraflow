---
id: 0303
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.865284+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Distinguish bare `str` from `str | None` before narrowing types

Narrowing a bare `str` field to a StrEnum is safe when all stored values conform, but narrowing `str | None` requires union narrowing, not direct replacement.

Example: Grep all state.json consumers and call sites exhaustively before narrowing; treat union fields separately.

**Why:** Narrowing a union type as if it were a bare type causes `ValidationError` on load for any stored `None` values.
