---
id: 0012
topic: gotchas
source_issue: 9442
source_phase: review
created_at: 2026-06-13T07:10:55.323944+00:00
status: active
corroborations: 1
---

# Error-tolerance tests must cover CreditExhaustedError re-raise, not just swallow

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
