---
id: 1476
topic: gotchas
source_issue: 11412
source_phase: plan
created_at: 2026-08-18T02:58:42.910244+00:00
status: active
corroborations: 1
---

# Don't raise CreditExhaustedError on parsed-but-invalid JSON

Raising `CreditExhaustedError` is justified only in the `parsed is None` branch of `DiagnosticRunner.diagnose()` — no valid JSON at all means the run was cut off. Do not raise it in the `model_validate` exception branch: a parsed-but-invalid block that merely quotes a cap is not authoritative.

**Why:** Raising on a non-authoritative block hands the orchestrator a false global pause, parking every loop instead of just the failover-affected one.
