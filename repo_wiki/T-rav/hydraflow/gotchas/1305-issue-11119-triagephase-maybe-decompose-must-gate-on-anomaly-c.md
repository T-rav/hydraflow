---
id: 1305
topic: gotchas
source_issue: 11119
source_phase: plan
created_at: 2026-08-14T12:19:29.537996+00:00
status: active
corroborations: 1
---

# TriagePhase._maybe_decompose must gate on anomaly-confirmed label

`TriagePhase._maybe_decompose` in `src/triage_phase.py` must return `False` for any `trust-loop-anomaly` issue lacking the `anomaly-confirmed` label. Confirmed escalations carry the label at file time in `src/trust_fleet_sanity_loop.py._file_anomaly`.

File-now-confirm-later does not work: triage reaches a fresh issue before the next 600s sanity tick, so a post-hoc label always loses the race.

**Why:** A single unconfirmed anomaly observation amplified into an epic + children defeats the confirmation guard.
