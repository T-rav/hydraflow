---
id: 1556
topic: gotchas
source_issue: 11889
source_phase: plan
created_at: 2026-09-01T10:19:26.410530+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Unknown Codex status: leave span open, log WARNING once

When a Codex `item.completed` event has a `status` not in `in_progress|completed|failed|declined`, log once at WARNING (literal format string, no interpolation) and leave the span open in `TraceCollector`. Do not default to `succeeded=True`.

**Why:** Treating an unrecognised status as success inflates success counts; leaving the span open surfaces the gap in later analysis rather than hiding it.
