---
id: 1388
topic: patterns
source_issue: 10913
source_phase: plan
created_at: 2026-07-31T13:38:55.527463+00:00
status: superseded
corroborations: 1
superseded_by: 1466
---

# ADR-0055 enumerates spans.py symbols — update list on additions

Rule: When adding a public symbol to `src/telemetry/spans.py`, append it to the enumerated symbol list in `docs/adr/0055-otel-honeycomb-instrumentation.md` (~line 101). Do not rely on `Skip-ADR:`.

Example: `reset_tracer_cache()` was added to the ADR-0055 symbol list alongside the existing `_get_tracer` entry.

**Why:** ADR-0055 bare-cites `src/telemetry/spans.py` and maintains an explicit public-surface inventory; stale lists cause ADR-vs-code drift that reviewers flag.
