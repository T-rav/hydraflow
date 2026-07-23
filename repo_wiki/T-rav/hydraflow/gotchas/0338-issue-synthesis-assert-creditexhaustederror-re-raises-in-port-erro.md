---
id: 0338
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.504625+00:00
status: superseded
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
superseded_by: 0348
---

# Assert CreditExhaustedError re-raises in port error-tolerance tests

When testing that a loop tolerates port failures, add a second case asserting `CreditExhaustedError` propagates instead of being swallowed.

Example: `port.side_effect = CreditExhaustedError("exhausted")` then `with pytest.raises(CreditExhaustedError): await loop._reconcile(...)` — see `test_review_phase_core.py:1919`.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract unchecked, letting a regression silently burn attempt budget against an exhausted billing signal.
