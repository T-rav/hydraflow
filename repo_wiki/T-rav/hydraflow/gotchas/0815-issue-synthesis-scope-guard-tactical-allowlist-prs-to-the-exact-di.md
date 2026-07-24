---
id: 0815
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:38:39.539884+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Scope-guard tactical allowlist PRs to the exact diff to avoid parent stall

When splitting a tactical fix off a stalled/broader parent issue (here, #10455 sliced from #10411's validated commit 92c9a12c), enforce the diff at review to just the two string literals plus a lineage comment in `src/adr_drift.py` and the new test file — widening into `_citation_drifts`, config, or the resolver loop reintroduces the complexity that stalled the parent.

**Why:** Scope creep back into the resolver is the exact failure mode the tactical split was meant to avoid.
