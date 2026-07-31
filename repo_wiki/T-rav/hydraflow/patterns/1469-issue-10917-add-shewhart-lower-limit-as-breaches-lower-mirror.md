---
id: 1469
topic: patterns
source_issue: 10917
source_phase: plan
created_at: 2026-07-31T16:16:35.877415+00:00
status: active
corroborations: 1
---

# Add Shewhart lower-limit as breaches_lower mirror

When adding a Shewhart signal for an adverse-when-LOW metric (e.g. setpoint density in `src/setpoint/`), implement it as a `breaches_lower` mirror of the existing `breaches_upper` in `src/vitals/control.py` — same API shape, opposite polarity. Suppress any breach when the baseline has fewer than `min_windows` observations. **Why:** Ad-hoc polarity flips at call sites make upper/lower asymmetric and let borderline values be re-classified by where the comparison lives.
