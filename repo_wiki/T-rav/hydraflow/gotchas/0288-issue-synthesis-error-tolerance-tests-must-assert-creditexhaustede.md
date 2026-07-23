---
id: 0288
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T06:25:49.694921+00:00
status: superseded
corroborations: 1
supersedes: 0282,0283,0284,0285,0286,0287
superseded_by: 0296
---

# Error-tolerance tests must assert CreditExhaustedError re-raises

Rule: When testing that a loop tolerates port failures, add a second case asserting `CreditExhaustedError` propagates instead of being swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` then `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)` — see `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked, letting a regression silently burn attempt budget against an exhausted billing signal.
