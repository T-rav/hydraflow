---
id: 1159
topic: gotchas
source_issue: 10726
source_phase: plan
created_at: 2026-07-27T18:34:31.163835+00:00
status: active
corroborations: 1
---

# Reason→title and reason→instructions must share one key set

`_SURFACE_REASON_TEXT` (`src/escape_ledger_loop.py:132`) and `_resolution_instructions` both dispatch on the same reason string. Unknown reasons fall back to the aging form in both mappings. A new reason added to one but not the other renders a title that promises one path while the body prints a different command. **Why:** Mismatched key sets silently misdirect operators to run the wrong resolution command, which cannot close the issue.
