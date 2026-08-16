---
id: 1431
topic: gotchas
source_issue: 11235
source_phase: plan
created_at: 2026-08-16T05:30:59.489365+00:00
status: active
corroborations: 1
---

# stream_claude_with_telemetry stays provider-blind; resolve at call sites

Never inject provider routing into `stream_claude_with_telemetry` — it is shared by `src/acceptance_criteria.py`, `src/verification_judge.py`, and `src/report_issue_loop.py`. Resolve provider at each call site and pass the resolved provider + rewritten `cmd` into the shared function. In `_run_precheck_context` closures, resolve from `self._config.ac_provider` inside the closure because `cmd` is a per-call parameter; `stream_claude_with_telemetry` re-derives `harness_env` from the provider it's handed.

**Why:** ADR-0134 mandates maintenance loops stay untouched; a blanket fix in the shared seam violates that boundary, and build-time resolution would freeze the wrong provider.
