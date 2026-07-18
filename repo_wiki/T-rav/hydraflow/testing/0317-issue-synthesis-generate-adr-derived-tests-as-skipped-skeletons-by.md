---
id: 0317
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.016346+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Generate ADR-derived tests as skipped skeletons by default

Extract the 4 baseline invariants (uniqueness, usage, negative, coverage) from an ADR's Decision section. Generate each test as a skipped skeleton.

Example: `@pytest.mark.skip(reason='skeleton: requires human review')`

**Why:** Auto-generating non-skipped tests from ambiguous ADR language creates brittle tests that break on legitimate wording updates without any real behavioral change.
