---
id: 0180
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.150523+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` followed by `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)`. See `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
