---
id: 0078
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.514813+00:00
status: superseded
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
superseded_by: 0112
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port/runner failures, always include a second case asserting `CreditExhaustedError` is *not* swallowed.

```python
# Case 1 — swallow
port.side_effect = RuntimeError("transient")
result = await loop._reconcile(...)  # no exception

# Case 2 — re-raise
port.side_effect = CreditExhaustedError("exhausted")
with pytest.raises(CreditExhaustedError):
    await loop._reconcile(...)
```

See `test_review_phase_core.py:1919` for the established pattern.

**Why:** `reraise_on_credit_or_bug` is a load-bearing call mandated by CLAUDE.md; testing only the swallow path leaves the re-raise contract completely unchecked.
