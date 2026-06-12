---
id: 0012
topic: gotchas
source_issue: 9080
source_phase: review
created_at: 2026-06-12T09:06:10.457707+00:00
status: active
corroborations: 1
---

# Null _adr_index to decouple prompt-length tests from corpus growth

In `tests/test_planner.py`, set `planner._adr_index = None` (or the equivalent null value) before asserting on prompt length or content.

```python
planner._adr_index = None
prompt = planner.build_prompt(issue)
assert len(prompt) < THRESHOLD
```

**Why:** An assertion tied to the live ADR corpus fails silently every time a new ADR is added, turning a correctness test into a corpus-size sensor.
