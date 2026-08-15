---
id: 2623
topic: testing
source_issue: 11192
source_phase: plan
created_at: 2026-08-15T00:51:35.394321+00:00
status: active
corroborations: 1
---

# Self-retire regression tests pinned to ADR filenames

Use `ADRIndex(_ADR_DIR).adrs()` lookup by ADR number with a `None` default and `pytest.skip` on missing/non-live — never hard-code ADR filenames like `_ADR_0007` with `parse_adr_file(...)`.

```python
adr = next((a for a in ADRIndex(_ADR_DIR).adrs() if a.number == 7), None)
if adr is None or not adr.is_live:
    pytest.skip("ADR-0007 retired")
```

**Why:** Routine ADR renumbering or retirement on an unrelated PR breaks CI with `FileNotFoundError` when tests pin to filenames that no longer exist.
