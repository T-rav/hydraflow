---
id: 0140
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.436854+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Auto-generated ADR tests must use @pytest.mark.skip by default

When auto-generating tests from ADR Decision sections, emit all tests with `@pytest.mark.skip(reason='skeleton: requires human review')`. Extract only 4 high-confidence baseline patterns per ADR: uniqueness, usage, negative, coverage.

**Why:** Automated pattern matching on ADR language is ambiguous; unskipped generated tests produce false-positive CI failures until a human validates each pattern.
