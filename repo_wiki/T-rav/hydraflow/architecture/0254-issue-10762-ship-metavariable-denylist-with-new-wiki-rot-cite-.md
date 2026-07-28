---
id: 0254
topic: architecture
source_issue: 10762
source_phase: plan
created_at: 2026-07-28T00:37:27.487529+00:00
status: active
corroborations: 1
---

# Ship metavariable denylist with new wiki-rot cite styles

Rule: When adding a new cite extraction style to `extract_cites`, the denylist (`_BARE_CITE_DENY`) must include metavariables the documentation will backtick (`snake_case`, `my_module`) from day one. The wiki entry documenting the style is itself scanned by the detector, creating self-referential false positives — the same class as #10595. Re-run the detector mentally over the doc edit before merge.

**Why:** Documentation examples trigger the very rot rule they describe, producing noise on the first tick after merge.
