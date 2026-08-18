---
id: 4063
topic: patterns
source_issue: 11423
source_phase: review
created_at: 2026-08-18T05:56:04.202006+00:00
status: active
corroborations: 1
---

# All production callers must pass `limit` by keyword across _PORT_FAKE_PAIRS

Every production call site that accepts `limit` must pass it as a keyword argument.

All 8-9 callers across `_PORT_FAKE_PAIRS`, including `src/review_insights.py`, currently do this. When adding new call sites, follow the same convention.

**Why:** Keyword-only passing ensures backward compatibility when the underlying Port/Fake signature changes; positional passing could silently misbehave or break.
