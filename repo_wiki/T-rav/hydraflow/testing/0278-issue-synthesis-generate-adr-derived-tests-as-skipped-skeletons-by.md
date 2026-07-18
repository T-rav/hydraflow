---
id: 0278
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:34:51.031085+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Generate ADR-derived tests as skipped skeletons by default

Extract the 4 baseline invariants (uniqueness, usage, negative, coverage) from an ADR's Decision section and generate each test with `@pytest.mark.skip(reason='skeleton: requires human review')`.

**Why:** Auto-generating non-skipped tests from ambiguous ADR language creates brittle tests that break on legitimate wording updates without any real behavioral change.
