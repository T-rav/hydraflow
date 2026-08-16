---
id: 3306
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:48.786739+00:00
status: superseded
corroborations: 1
supersedes: 3173
superseded_by: 3443
---

# adds_regression_pin shortcut is sole evidence path for zero-needle rows

Do not replace `adds_regression_pin` (in `src/escape/attribution.py`) with a `regression_hits` grep. ~36% of ledger rows have no issue ref and no originating SHA, so the shortcut is their only resolution path.

Example: Swapping it silently stops those rows from auto-resolving. The guard: a dedicated zero-needle test in `tests/test_escape_auto_diagnose.py`.

**Why:** A grep-based approach issues no needles and returns nothing, silently re-breaking rows that the shortcut currently closes.
