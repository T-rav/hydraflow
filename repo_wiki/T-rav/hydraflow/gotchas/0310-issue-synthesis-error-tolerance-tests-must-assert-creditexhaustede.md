---
id: 0310
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:09:59.033218+00:00
status: superseded
corroborations: 1
supersedes: 0302,0303,0304,0305,0306,0307,0308,0309
superseded_by: 0317
---

# Error-tolerance tests must assert CreditExhaustedError re-raises

When testing that a loop tolerates port failures, add a second case asserting `CreditExhaustedError` propagates instead of being swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` then `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)` — see `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked, letting a regression silently burn attempt budget against an exhausted billing signal.
