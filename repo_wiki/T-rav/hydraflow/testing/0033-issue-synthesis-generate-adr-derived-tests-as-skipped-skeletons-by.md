---
id: 0033
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.411637+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Generate ADR-derived tests as skipped skeletons by default

Extract the 4 baseline invariants (uniqueness, usage, negative, coverage) from an ADR's Decision section. Generate each test with:

```python
@pytest.mark.skip(reason="skeleton: requires human review")
```

**Why:** Auto-generating non-skipped tests from ambiguous ADR language creates brittle tests that break on legitimate wording updates without any real behavioral change.
