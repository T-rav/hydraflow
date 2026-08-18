---
id: 0398
topic: architecture
source_issue: 11412
source_phase: plan
created_at: 2026-08-18T02:58:42.910196+00:00
status: active
corroborations: 1
---

# Route failover-lane fallbacks through one shared predicate

Define one module-level private predicate (e.g. `_failover_infra()`) and call it from every fallback branch in `DiagnosticRunner.diagnose()` (`src/diagnostic_runner.py`) that classifies a failover-lane failure as INFRA. Keep the deferred `from credit_failover import is_active` inside the predicate body. Both the `parsed is None` branch (~line 219) and the `DiagnosisResult.model_validate` exception branch (~line 230) must call the same predicate.

**Why:** Sibling branches that re-state the import or expression at two sites will drift, silently re-splitting one failure class into two.
