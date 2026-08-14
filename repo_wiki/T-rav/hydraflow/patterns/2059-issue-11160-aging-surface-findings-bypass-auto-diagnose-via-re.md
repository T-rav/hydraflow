---
id: 2059
topic: patterns
source_issue: 11160
source_phase: plan
created_at: 2026-08-14T18:34:20.225946+00:00
status: active
corroborations: 1
---

# Aging surface findings bypass auto-diagnose via reason filter

`_auto_diagnose` (`src/escape_ledger_loop.py:601`) pre-filters on `reason != SURFACE_REASON_LOW_CONFIDENCE`, so aging findings are never machine-diagnosed. Regression-pin rows are born at `attribution_confidence="medium"` (`escape/detect.py::_classify`), so they can never enter `metrics.low_confidence` — aging is their only reachable surface.

**Why:** Medium-confidence escapes get stranded on the aging surface with no machine resolution path, forcing unnecessary HITL.
