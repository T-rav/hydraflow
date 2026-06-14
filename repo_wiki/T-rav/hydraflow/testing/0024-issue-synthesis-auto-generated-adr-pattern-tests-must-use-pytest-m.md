---
id: 0024
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.830164+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Auto-generated ADR pattern tests must use @pytest.mark.skip by default

When auto-generating tests from ADR Decision sections, emit all tests with `@pytest.mark.skip(reason="skeleton: requires human review")`. Extract only 4 high-confidence baseline patterns per ADR: uniqueness, usage, negative, coverage.

**Why:** Automated pattern matching on ADR language is ambiguous; unskipped generated tests produce false-positive CI failures until a human validates each pattern.
