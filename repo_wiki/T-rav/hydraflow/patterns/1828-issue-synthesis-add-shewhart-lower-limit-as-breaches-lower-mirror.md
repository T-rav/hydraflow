---
id: 1828
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.308845+00:00
status: superseded
corroborations: 1
supersedes: 1732
superseded_by: 1926
---

# Add Shewhart lower-limit as breaches_lower mirror

When adding a Shewhart signal for an adverse-when-LOW metric, implement it as a `breaches_lower` mirror of the existing `breaches_upper` in `src/vitals/control.py` — same API shape, opposite polarity. Suppress any breach when the baseline has fewer than `min_windows` observations.

Example: Setpoint density in `src/setpoint/` uses the `breaches_lower` mirror pattern.

**Why:** Ad-hoc polarity flips at call sites make upper/lower asymmetric and let borderline values be re-classified by where the comparison lives.
