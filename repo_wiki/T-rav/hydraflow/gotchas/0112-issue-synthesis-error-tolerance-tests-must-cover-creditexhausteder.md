---
id: 0112
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.463210+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port/runner failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

Example: Case 1 sets `port.side_effect = RuntimeError("transient")` and expects no exception; Case 2 sets `port.side_effect = CreditExhaustedError("exhausted")` and expects `pytest.raises(CreditExhaustedError)`. See `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is load-bearing per CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
