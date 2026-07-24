---
id: 0592
topic: gotchas
source_issue: 10433
source_phase: plan
created_at: 2026-07-24T10:22:54.781315+00:00
status: superseded
corroborations: 1
superseded_by: 0593
---

# Symbol-qualify ADR citations to stop bare-file drift false positives

A bare ADR source citation like `` `src/issue_fetcher.py` `` drifts on *any* touch to that file, even unrelated additions (e.g. PR #10417's `IssueFetcher._is_open` triggered ADR-0019 drift despite no cache/TTL logic change). Qualify with `:Symbol` — e.g. `src/issue_fetcher.py:IssueFetcher._get_collaborators` — so `adr_drift._citation_drifts` only fires on symbol-level evidence, which production `gh` diffs rarely supply for untouched methods.

**Why:** prevents recurring false-positive ADR drift rollups (ADR-0019 rollup #10433) without suppressing genuine regressions to the cited method.
