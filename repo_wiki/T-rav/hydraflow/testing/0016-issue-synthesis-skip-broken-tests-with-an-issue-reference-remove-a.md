---
id: 0016
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409375+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Skip broken tests with an issue reference; remove after fix

Mark broken tests with a referenced issue, never a bare skip:

```python
@pytest.mark.skip(reason="documenting bug: #1234")
```

Remove the skip immediately after the issue is resolved.

**Why:** Without an issue reference, skipped tests become permanent dead weight with no path to removal or triage.
