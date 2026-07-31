---
id: 1247
topic: gotchas
source_issue: 10890
source_phase: plan
created_at: 2026-07-31T12:12:42.365167+00:00
status: active
corroborations: 1
---

# ADR-0055 bare-cites `src/trace_collector.py`; edits trigger drift

ADR-0055 (docs/adr/0055-otel-honeycomb-instrumentation.md) grants whole-file ownership via backtick spans. Modifying a cited file without updating ADR prose trips `AdrTouchpointAuditor` drift rollups in `make quality`.

- When touching `src/trace_collector.py`, update ADR-0055 emit-site prose (e.g., add `_add_tool_call` alongside `_record_inner` at :112).
- `make quality` runs ADR/arch gates over the full tree, not a file subset.

**Why:** ADR drift rollups fail `make quality` even when code is correct; prose touchpoints are mandatory, not cosmetic.
