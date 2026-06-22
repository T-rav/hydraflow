---
id: 0110
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.084342+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Auto-generated ADR tests must use @pytest.mark.skip by default

When auto-generating tests from ADR Decision sections, emit all tests with `@pytest.mark.skip(reason='skeleton: requires human review')`. Extract only 4 high-confidence baseline patterns per ADR: uniqueness, usage, negative, coverage.

**Why:** Automated pattern matching on ADR language is ambiguous; unskipped generated tests produce false-positive CI failures until a human validates each pattern.
