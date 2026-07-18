---
id: 0243
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T15:01:50.872044+00:00
status: active
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
---

# Generate ADR-derived tests as skipped skeletons by default

When auto-generating tests from ADR Decision sections, emit all tests with `@pytest.mark.skip(reason='skeleton: requires human review')`. Extract only 4 high-confidence baseline patterns per ADR: uniqueness, usage, negative, coverage.

**Why:** Automated pattern matching on ADR language is ambiguous; unskipped generated tests produce false-positive CI failures on legitimate wording updates.
