---
id: 1951
topic: patterns
source_issue: 11144
source_phase: plan
created_at: 2026-08-14T14:39:13.298864+00:00
status: superseded
corroborations: 1
superseded_by: 2057
---

# _auto_diagnose: drop reason filter; only INCONCLUSIVE reaches human

`_auto_diagnose` in `src/escape_ledger_loop.py` must drop its `reason != SURFACE_REASON_LOW_CONFIDENCE` pre-filter. Every eligible surfacing pair is diagnosed; only `INCONCLUSIVE` residue is filed to a human.

- Aging findings (`escape_ledger_encoding_age_days=0` makes a fresh row aging) are machine-diagnosed before filing.
- With auto-diagnose disabled, filing behaviour is unchanged.
- The lazy alternative — `resolve_escape(..., "high")` — promotes false positives into escapes-per-100-merges; do not use it.

**Why:** Filtering by reason leaves aging escapes un-diagnosed, causing human asks for machine-dismissable rows.
