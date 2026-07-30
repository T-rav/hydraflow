---
id: 0217
topic: architecture
source_issue: 10575
source_phase: plan
created_at: 2026-07-26T00:41:55.611407+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Wiki entries can assert unbuilt mechanisms — verify before citing

repo_wiki entries written during a plan phase may describe proposed mechanisms that never actually shipped. Entries 0204/0842/0843 under `repo_wiki/T-rav/hydraflow/` cited `DETECTOR_GENERATION`, `dedupe_by_detection_ref`, `boundary_sha_before_days`, and `gauge_calibration()` — none exist in `src/escape/*`; the PR closing the originating issue (#10548 for #10504) shipped only a regression test, not the described mechanism. Before treating a wiki entry as architecture, grep its cited symbols against `src/`. **Why:** prevents future planners from designing on top of fictional APIs that only ever existed as a plan-phase proposal.
