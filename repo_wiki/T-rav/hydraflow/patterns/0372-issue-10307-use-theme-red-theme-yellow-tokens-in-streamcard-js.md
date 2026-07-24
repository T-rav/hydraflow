---
id: 0372
topic: patterns
source_issue: 10307
source_phase: plan
created_at: 2026-07-24T04:05:15.039825+00:00
status: superseded
corroborations: 1
superseded_by: 0373
---

# Use theme.red/theme.yellow tokens in StreamCard.jsx, never literal hex

Color assignments in `src/ui/src/components/StreamCard.jsx` (e.g. `StageRow`'s `nodeStyle`) must reference `theme.*` tokens (`theme.red`, backed by CSS var `--red`) rather than hardcoded hex values. Regression tests should assert against the same token string the component sets (e.g. `theme.red`), matching the convention used in the existing `StageRow queued presentation` test in `StreamCard.test.jsx`.

**Why:** a literal hex value bypasses the light/dark theming system and breaks visual consistency across themes.
