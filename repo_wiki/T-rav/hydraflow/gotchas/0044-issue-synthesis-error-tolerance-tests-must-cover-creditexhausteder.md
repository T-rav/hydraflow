---
id: 0044
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.904503+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Error-tolerance tests must cover CreditExhaustedError re-raise, not just swallow

When testing that a loop tolerates port/runner failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

- Swallow: `port.side_effect = RuntimeError("transient")` → no exception
- Re-raise: `port.side_effect = CreditExhaustedError("exhausted")` → `pytest.raises(...)`

See `test_review_phase_core.py:1919` for the pattern.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
