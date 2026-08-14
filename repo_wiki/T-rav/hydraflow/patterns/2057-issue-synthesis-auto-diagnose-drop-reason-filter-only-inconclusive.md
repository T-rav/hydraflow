---
id: 2057
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.858753+00:00
status: active
corroborations: 1
supersedes: 1951
---

# _auto_diagnose: drop reason filter; only INCONCLUSIVE reaches human

`_auto_diagnose` in `src/escape_ledger_loop.py` must drop its `reason != SURFACE_REASON_LOW_CONFIDENCE` pre-filter — every eligible surfacing pair is diagnosed, only `INCONCLUSIVE` residue reaches a human.

Example: Aging findings are machine-diagnosed before filing; with auto-diagnose disabled, filing behaviour is unchanged. Do not use `resolve_escape(..., "high")` — it promotes false positives into escapes-per-100-merges.

**Why:** Filtering by reason leaves aging escapes un-diagnosed, causing human asks for machine-dismissable rows.
