---
id: 2393
topic: testing
source_issue: 11115
source_phase: plan
created_at: 2026-08-14T10:03:17.496182+00:00
status: active
corroborations: 1
---

# Baseline exemption entries must still cite a §

Entries in `tests/architecture/spec_citation_baseline.json` must still contain at least one `§` citation. The shrink-only guard in `tests/architecture/test_spec_citations_resolve.py` fails if a baseline entry no longer cites any `§` — the entry must be removed, not left as a permanent exemption.

**Why:** Without this guard, baseline entries rot into permanent waivers and the citation debt never actually drains.
