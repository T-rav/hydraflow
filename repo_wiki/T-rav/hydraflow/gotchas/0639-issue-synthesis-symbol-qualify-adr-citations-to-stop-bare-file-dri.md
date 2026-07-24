---
id: 0639
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.745228+00:00
status: active
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# Symbol-qualify ADR citations to stop bare-file drift false positives

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` determines drift from `gh`'s file-level PR diff — it has no visibility into which symbols within a file changed, so a bare citation like `` `src/issue_fetcher.py` `` drifts on any touch to that file, even unrelated ones.

Example: PR #10417's `IssueFetcher._is_open` triggered ADR-0019 drift despite no cache/TTL logic change. Qualify with `:Symbol` — e.g. `src/issue_fetcher.py:IssueFetcher._get_collaborators` — so `_citation_drifts` only fires on symbol-level evidence, which production `gh` diffs rarely supply for untouched methods.

**Why:** Prevents recurring false-positive ADR drift rollups (ADR-0019 rollup #10433) without suppressing genuine regressions to the cited method.
