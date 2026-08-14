---
id: 0301
topic: architecture
source_issue: 11089
source_phase: plan
created_at: 2026-08-14T06:37:49.577202+00:00
status: active
corroborations: 1
---

# Detector thresholds are bare module constants, not config fields

Thresholds and floors in detector modules live as bare module-level constants (e.g. `prompt_efficiency.INEFFICIENCY_THRESHOLD`, `prompt_efficiency.MIN_WINDOW_CALLS`), keyword-overridable at call sites — not as config fields. Keep new ones public (no leading underscore) when imported across modules (the loop imports `MIN_WINDOW_CALLS`).

**Why:** Matches in-repo precedent, keeps the detector self-contained without coupling to the config schema, and avoids persisted-state migration.
