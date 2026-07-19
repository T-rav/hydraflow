---
id: 0146
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.947225+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` followed by `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)`. See `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
