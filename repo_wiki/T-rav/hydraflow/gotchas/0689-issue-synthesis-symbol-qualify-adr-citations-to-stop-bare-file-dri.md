---
id: 0689
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.487921+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Symbol-qualify ADR citations to stop bare-file drift false positives

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` determines drift from `gh`'s file-level PR diff — it has no visibility into which symbols within a file changed, so a bare citation like `` `src/issue_fetcher.py` `` drifts on any touch to that file, even unrelated ones.

Example: PR #10417's `IssueFetcher._is_open` triggered ADR-0019 drift despite no cache/TTL logic change. Qualify with `:Symbol` — e.g. `src/issue_fetcher.py:IssueFetcher._get_collaborators` — so `_citation_drifts` only fires on symbol-level evidence, which production `gh` diffs rarely supply for untouched methods.

**Why:** Prevents recurring false-positive ADR drift rollups (ADR-0019 rollup #10433) without suppressing genuine regressions to the cited method.
