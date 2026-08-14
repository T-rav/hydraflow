---
id: 0315
topic: architecture
source_issue: 11117
source_phase: plan
created_at: 2026-08-14T10:58:30.492120+00:00
status: active
corroborations: 1
---

# Fall back to lifetime rate when no baseline exists in prompt_efficiency detectors

Pure rate detectors in `prompt_efficiency.py` must handle sources with no stored baseline by judging on lifetime totals, mirroring `cost_per_call`'s existing fallback pattern. A baseline missing the anomaly key must clamp the computed rate to ≤ 1.0. Sources below a min-call floor are skipped regardless of rate.
Example: `detect_zero_usage_sources(totals_by_source, baseline, *, rate_threshold, min_calls)`
**Why:** Without the fallback, sources that predate baseline tracking are silently invisible to the detector.
