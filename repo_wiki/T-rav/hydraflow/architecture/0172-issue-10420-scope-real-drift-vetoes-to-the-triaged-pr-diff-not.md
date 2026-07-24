---
id: 0172
topic: architecture
source_issue: 10420
source_phase: plan
created_at: 2026-07-24T06:29:23.521327+00:00
status: active
corroborations: 1
---

# Scope REAL_DRIFT vetoes to the triaged PR diff, not the whole ADR's citations

In `src/adr_drift_resolver_loop.py`, when recording a `DriftClassification.REAL_DRIFT` veto via `add_real_drift_vetoes`, only include the ADR's bare-cited `src/` modules that are actually present in the triaged PR's diff — not every module the ADR cites.

**Why:** un-scoped vetoes would remove suppression from genuinely-shared modules that merely co-occur in the same ADR's citation list but weren't part of the real-drift change, causing false-positive drift findings elsewhere.
