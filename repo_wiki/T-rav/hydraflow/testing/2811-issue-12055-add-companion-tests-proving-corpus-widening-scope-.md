---
id: 2811
topic: testing
source_issue: 12055
source_phase: plan
created_at: 2026-09-02T21:55:38.779839+00:00
status: active
corroborations: 1
---

# Add companion tests proving corpus-widening scope is live and catches new formats

When widening a compliance-check corpus, add specs verifying the scan actually covers new document types and includes new paths.

Example (test_beads_manager.py): Test that the regex constant catches `bd create` in doc prose, and that corpus includes at least one tracked `docs/wiki/*.md` path.

**Why:** Without companion tests, future maintainers cannot distinguish whether widening is active and may safely re-narrow without triggering guard reddening.
