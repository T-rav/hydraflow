---
id: 0684
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.848062+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers

Changes to `TrustFleetSanityLoop`'s staleness detection require the full pyramid per `docs/standards/testing/README.md`: unit tests in `tests/test_trust_fleet_anomaly_detectors.py` for the floor math, a wiring test in `tests/test_trust_fleet_sanity_loop.py` for call-site fallback behavior, a red→green regression in `tests/regressions/test_issue_10236.py` against real config defaults, and a MockWorld scenario in `tests/scenarios/test_trust_fleet_sanity_scenario.py` covering both a fast-poll/long-cycle worker (no escalation) and an existing slow-poll worker like flake_tracker (escalation unchanged).

**Why:** unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold happen to agree for slow-poll workers but diverge for fast-poll ones — only a scenario exercising both worker profiles proves the fix doesn't regress existing escalations.
