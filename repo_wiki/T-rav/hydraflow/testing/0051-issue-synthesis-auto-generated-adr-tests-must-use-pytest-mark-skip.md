---
id: 0051
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.213362+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Auto-generated ADR tests must use @pytest.mark.skip by default

When auto-generating tests from ADR Decision sections, emit all tests with `@pytest.mark.skip(reason="skeleton: requires human review")`. Extract only 4 high-confidence baseline patterns per ADR: uniqueness, usage, negative, coverage.

**Why:** Automated pattern matching on ADR language is ambiguous; unskipped generated tests produce false-positive CI failures until a human validates each pattern.
