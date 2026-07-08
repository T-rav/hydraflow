---
id: 0170
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.579759+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Auto-generated ADR tests must use @pytest.mark.skip by default

When auto-generating tests from ADR Decision sections, emit all tests with `@pytest.mark.skip(reason='skeleton: requires human review')`. Extract only 4 high-confidence baseline patterns per ADR: uniqueness, usage, negative, coverage.

**Why:** Automated pattern matching on ADR language is ambiguous; unskipped generated tests produce false-positive CI failures until a human validates each pattern.
