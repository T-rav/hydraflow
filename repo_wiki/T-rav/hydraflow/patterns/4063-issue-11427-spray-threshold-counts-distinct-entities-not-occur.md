---
id: 4063
topic: patterns
source_issue: 11427
source_phase: plan
created_at: 2026-08-18T04:40:50.671737+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Spray threshold counts distinct entities, not occurrences

The `detector_calibration_spray_min_entities` config field (default 5, `ge=3`, `le=100`, env override `HYDRAFLOW_DETECTOR_CALIBRATION_SPRAY_MIN_ENTITIES`) must count **distinct** entities, not total occurrences.

- Threshold floor of 3 is deliberately above the 3-PR shape that produced #11405's fabricated churn.
- One entity escalating 20× stays subject-class only; 5 distinct entities each escalating once triggers spray.

**Why:** Counting occurrences instead of distinct entities lets a single noisy entity trip the spray detector, recreating #11405.
