---
id: 0025
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.410503+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Sync test label constants with production pipeline definitions

Keep test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) synchronized with production definitions. Use dynamic length checks:

```python
assert len(LABELS) == len(ALL_PIPELINE_LABELS)
```

Test both `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` paths independently.

**Why:** Stale test constants let new label additions pass CI without being exercised by the test suite.
