---
id: 2749
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T10:07:01.977289+00:00
status: superseded
corroborations: 1
supersedes: 2626
superseded_by: 2878
---

# ADR-0055 enumerates spans.py symbols — update list on additions

When adding a public symbol to `src/telemetry/spans.py`, append it to the enumerated symbol list in `docs/adr/0055-otel-honeycomb-instrumentation.md` (~line 101). Do not rely on `Skip-ADR:`.

Example: `reset_tracer_cache()` was added to the ADR-0055 symbol list alongside the existing `_get_tracer` entry.

**Why:** ADR-0055 bare-cites `src/telemetry/spans.py` and maintains an explicit public-surface inventory; stale lists cause ADR-vs-code drift that reviewers flag.
