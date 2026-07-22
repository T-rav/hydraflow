---
id: 0248
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.014412+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` followed by `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)`. See `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
