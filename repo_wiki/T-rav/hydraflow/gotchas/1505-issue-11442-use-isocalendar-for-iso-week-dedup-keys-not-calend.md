---
id: 1505
topic: gotchas
source_issue: 11442
source_phase: plan
created_at: 2026-08-18T08:00:27.527801+00:00
status: active
corroborations: 1
---

# Use isocalendar() for ISO-week dedup keys, not calendar year

Build weekly dedup keys as `token_drift:<source>:<ISO year>-W<week>` using `datetime.isocalendar()`, not `strftime('%Y-W%W')`. A 2026-12-31 timestamp belongs to ISO year 2027, week 1 — the calendar year would produce a different key and file duplicate issues.

**Why:** `isocalendar()` is the only Python API that correctly maps year-boundary dates to their ISO week; calendar-year formats silently split one ISO week across two keys.
