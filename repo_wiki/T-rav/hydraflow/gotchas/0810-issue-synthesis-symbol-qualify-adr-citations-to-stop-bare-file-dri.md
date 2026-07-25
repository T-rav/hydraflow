---
id: 0810
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:04.011229+00:00
status: superseded
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
superseded_by: 0851
---

# Symbol-qualify ADR citations to stop bare-file drift false positives

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` determines drift from `gh`'s file-level PR diff — it has no visibility into which symbols within a file changed, so a bare citation like `` `src/issue_fetcher.py` `` drifts on any touch to that file, even unrelated ones.

Example: PR #10417's `IssueFetcher._is_open` triggered ADR-0019 drift despite no cache/TTL logic change. Qualify with `:Symbol` — e.g. `src/issue_fetcher.py:IssueFetcher._get_collaborators` — so `_citation_drifts` only fires on symbol-level evidence, which production `gh` diffs rarely supply for untouched methods.

**Why:** Prevents recurring false-positive ADR drift rollups (ADR-0019 rollup #10433) without suppressing genuine regressions to the cited method.
