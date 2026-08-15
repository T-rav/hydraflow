---
id: 2303
topic: patterns
source_issue: 11185
source_phase: review
created_at: 2026-08-15T03:31:43.632107+00:00
status: stale
corroborations: 1
stale_reason: source issue #11185 closed
---

# EscapeRecord.notes is always str (never None) — no None-guard needed

`EscapeRecord.notes` is typed `str` (`src/escape/models.py:111`) and defaulted to `""` on parse (`models.py:176`). Sanitizers like `_sanitize_evidence_cell` in `src/escape/report.py` need no `if notes is None` guard — the parse path guarantees a string.

**Why:** Adding defensive None-checks is dead code that misleads future contributors into thinking a None path exists.
