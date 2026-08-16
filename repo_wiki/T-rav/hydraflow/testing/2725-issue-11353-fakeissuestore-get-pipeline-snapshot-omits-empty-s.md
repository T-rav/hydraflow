---
id: 2725
topic: testing
source_issue: 11353
source_phase: plan
created_at: 2026-08-16T14:57:57.978690+00:00
status: active
corroborations: 1
---

# FakeIssueStore.get_pipeline_snapshot omits empty stages — inject at wire

MockWorld's `FakeIssueStore.get_pipeline_snapshot` (`fake_issue_store.py:425`) omits stages with no issues entirely, so it cannot reproduce a boot-window payload where every stage key maps to `[]`. To model a mid-restart empty snapshot, inject at the wire boundary via Playwright `page.route` fulfilling `/api/pipeline`, not through fake-store internals.

**Why:** Keeps the test independent of backend readiness issues (#11215/#11279) and reproduces the exact byte-indistinguishable empty payload that triggers the defect.
