---
id: 3031
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:48.384197+00:00
status: superseded
corroborations: 1
supersedes: 2904
superseded_by: 3165
---

# _auto_diagnose: drop reason filter; only INCONCLUSIVE reaches human

`_auto_diagnose` in `src/escape_ledger_loop.py` must drop its `reason != SURFACE_REASON_LOW_CONFIDENCE` pre-filter — every eligible surfacing pair is diagnosed, only `INCONCLUSIVE` residue reaches a human.

Example: Regression-pin rows are born at `attribution_confidence="medium"` (`escape/detect.py::_classify`), so aging is their only reachable surface. Without dropping the filter, medium-confidence escapes strand on the aging surface with no machine resolution path. Do not use `resolve_escape(..., "high")` — it promotes false positives.

**Why:** Filtering by reason leaves aging escapes un-diagnosed, causing human asks for machine-dismissable rows.
