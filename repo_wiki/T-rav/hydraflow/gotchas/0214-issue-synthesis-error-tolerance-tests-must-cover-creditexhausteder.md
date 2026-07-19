---
id: 0214
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.791976+00:00
status: active
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` followed by `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)`. See `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked.
