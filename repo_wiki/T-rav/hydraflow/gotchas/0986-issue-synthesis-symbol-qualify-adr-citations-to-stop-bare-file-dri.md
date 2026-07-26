---
id: 0986
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.194006+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# Symbol-qualify ADR citations to stop bare-file drift false positives

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` determines drift from `gh`'s file-level PR diff — it has no visibility into which symbols within a file changed, so a bare citation like `` `src/issue_fetcher.py` `` drifts on any touch to that file, even unrelated ones.

Example: PR #10417's `IssueFetcher._is_open` triggered ADR-0019 drift despite no cache/TTL logic change. Qualify with `:Symbol` — e.g. `src/issue_fetcher.py:IssueFetcher._get_collaborators` — so `_citation_drifts` only fires on symbol-level evidence, which production `gh` diffs rarely supply for untouched methods.

**Why:** Prevents recurring false-positive ADR drift rollups (ADR-0019 rollup #10433) without suppressing genuine regressions to the cited method.
