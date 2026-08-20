---
id: 1519
topic: gotchas
source_issue: 11480
source_phase: plan
created_at: 2026-08-20T06:54:25.786713+00:00
status: active
corroborations: 1
---

# Terminal guard scans: try/except → reraise_on_credit_or_bug → return False

Wrap pre-decomposition guard scans in `try/except Exception` → `reraise_on_credit_or_bug(exc)` → `logger.warning(literal_format_string)` → return False.

- Keeps `prs = AsyncMock()` unit tests green: iterating a MagicMock raises, swallowed here.
- Fail-open preserves today's decomposition behavior on transient errors.

**Why:** Without this, adding a landed-fix guard turns every pre-existing `AsyncMock()` test into a failure because MagicMock iteration raises at runtime.
