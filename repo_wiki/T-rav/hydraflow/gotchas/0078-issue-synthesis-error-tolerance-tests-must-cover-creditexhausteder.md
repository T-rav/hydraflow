---
id: 0078
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.481383+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

Always include a second case asserting `CreditExhaustedError` is re-raised alongside any error-tolerance test that swallows port/runner failures.

Example: test `RuntimeError` is swallowed (no exception), then test `CreditExhaustedError` is re-raised via `pytest.raises(CreditExhaustedError)`. See `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is load-bearing per CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
