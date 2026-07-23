---
id: 0044
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.331261+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Error-tolerance tests must cover CreditExhaustedError re-raise

When testing that a loop tolerates port/runner failures, always include a second case that asserts `CreditExhaustedError` is *not* swallowed.

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
